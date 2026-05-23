"""ChatAgent: conversational assistant with tool-calling for the monitoring dashboard.

Context management follows a hybrid "sliding window + exchange-boundary" strategy
inspired by industry practices:

- Anthropic Claude / OpenAI ChatGPT: sliding window with token budget, trimming
  oldest turns when budget exceeded
- LangChain ConversationTokenBufferMemory: token-limit-based trimming
- OpenAI Assistants API: tool messages (assistant tool_calls + tool results) are
  persisted across turns so the model remembers prior tool interactions
- Microsoft Guidance: exchange-granularity — trim complete user↔assistant rounds,
  never split a tool-call sequence mid-exchange

Key design decisions:
- Token estimation via character-class heuristic (no tiktoken dependency; glm-4-flash
  tokenizer is not publicly available anyway)
- Trim by complete "exchanges": user → (assistant tool_calls → tool result)* → assistant
- Always keep ≥1 exchange to preserve conversation continuity
- Return context stats in every response so the frontend can surface usage
"""

import json
import logging
import re

import httpx
from bs4 import BeautifulSoup

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

# ── HTML cleaning (shared with fetcher) ────────────────────────────────
SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
WHITESPACE_RE = re.compile(r"\s+")

# ── Token estimation helpers ───────────────────────────────────────────
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_ENGLISH_RE = re.compile(r"[a-zA-Z]+")


def _count_tokens(text: str) -> int:
    """Estimate token count for Chinese + English mixed text.

    Heuristic calibrated against typical multilingual tokenizers:
    - Chinese character ≈ 1.2 tokens (most tokenizers encode 1 char ≈ 1–2 tokens)
    - English word ≈ 1.3 tokens (subword tokenization)
    - Other characters ≈ 0.3 tokens (whitespace, punctuation merge with neighbors)
    """
    chinese = len(_CHINESE_RE.findall(text))
    english = len(_ENGLISH_RE.findall(text))
    other = len(text) - chinese - english
    return int(chinese * 1.2 + english * 1.3 + other * 0.3)


def _messages_tokens(messages: list[dict]) -> int:
    """Total estimated tokens across a message list."""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, str):
            total += _count_tokens(content)
        if m.get("tool_calls"):
            for tc in m["tool_calls"]:
                args = tc.get("function", {}).get("arguments", "")
                total += _count_tokens(args) + 10  # +10 for JSON structure overhead
    return total


# ── HTTP fetch config ──────────────────────────────────────────────────
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ── Tool definitions ───────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_news",
            "description": "查询数据库中存储的新闻/论文条目，支持按站点、标签筛选。返回标题、标签、日期",
            "parameters": {
                "type": "object",
                "properties": {
                    "site_name": {
                        "type": "string",
                        "description": "站点名称：baidu_news / sina_news / deepmind_blog / openai_blog。不传查全部",
                    },
                    "tag": {
                        "type": "string",
                        "description": "标签筛选，如 科技/财经/国际/AI研究",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数上限，默认 10",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": "获取指定站点的最新运行统计：最近状态、抓取条目数、变更数、标签分布、更新时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "site_name": {
                        "type": "string",
                        "description": "站点名称，如 baidu_news / sina_news",
                    }
                },
                "required": ["site_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_semantic",
            "description": "语义搜索已有新闻/论文标题，按语义相似度排序。适合用户用自然语言描述想找的内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "自然语言搜索描述"},
                    "site_name": {
                        "type": "string",
                        "description": "限定站点，不传搜全部",
                    },
                    "limit": {"type": "integer", "description": "返回结果数，默认 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_article",
            "description": "抓取指定 URL 的正文内容并用 AI 生成中文摘要。当用户想了解某篇新闻/文章的具体内容时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "文章链接 URL"},
                    "title": {
                        "type": "string",
                        "description": "文章标题（可选，帮助生成更准确的摘要）",
                    },
                },
                "required": ["url"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是 News Agent Monitor 的智能对话助手，帮助用户查询和分析新闻/论文监控数据。

## 项目架构

本系统自动监控多个新闻和论文网站，定时抓取、提取、对比变化并生成可视化图表。

### 数据存储
- SQLite 数据库：`data/monitor.db`（新闻）+ `data/papers.db`（论文）
- snapshots 表：抓取的条目（title, url, tag, site_name, content_hash, snapshot_time）
- run_history 表：每次 pipeline 运行记录（status, items_found, changes_detected, duration）
- metadata 表：站点元信息（标签分布, 更新时间, 运行统计）

### Pipeline 流程
Fetch（httpx/Playwright 抓取网页）→ Parse（LLM 提取新闻+分类打标签）→ Analyze（对比历史快照计算 diff + LLM 生成变更摘要）→ Visualize（matplotlib + ECharts 生成图表）→ Notify（可选：钉钉/企业微信/邮件推送）

### 监控站点
| 站点 | 类型 | 抓取方式 | 频率 | 常见标签 |
|------|------|----------|------|----------|
| baidu_news | 新闻 | Playwright 浏览器 | 60 min | 科技, 要闻, 财经, 军事, 娱乐, 国内, 国际, 体育 |
| sina_news | 新闻 | httpx 静态 | 120 min | 国际, 体育, 社会, 财经, 国内, 军事, 汽车, 其他 |
| deepmind_blog | 论文 | RSS feed | 360 min | AI研究 |
| openai_blog | 论文 | RSS feed | 360 min | AI研究 |

### 重要说明
- deepmind.google 在国内被 GFW 阻断（TLS 层），deepmind_blog 大概率抓取失败，非系统故障
- 新闻站点（baidu_news, sina_news）的标签由 LLM 自动分类，论文站点标签固定为 "AI研究"
- 变更检测通过 content_hash 对比，相同标题+URL 内容变化视为 modified

## 回答要求
- 使用中文回复，简洁准确（通常 2-5 句）
- 所有数据必须来自工具查询结果，不要编造
- 查询无结果时如实说明，建议调整筛选条件
- 关于项目本身的问题（站点列表、架构等）直接根据上述知识回答，无需调用工具"""

MAX_TOOL_ROUNDS = 3
MAX_HISTORY_TOKENS = (
    4000  # budget for _history only; system prompt + response use separate budget
)
MIN_EXCHANGES = 1  # always keep at least this many exchanges


class ChatAgent(BaseAgent):
    """Conversational assistant backed by tool-calling LLM.

    Context management: hybrid sliding window with exchange-boundary trimming.
    Each "exchange" = user message → (tool_calls → result)* → assistant reply.
    When the token budget is exceeded, the oldest complete exchanges are removed.
    """

    def __init__(
        self,
        config: dict,
        news_store=None,
        paper_store=None,
        vector_store=None,
        max_history_tokens: int = MAX_HISTORY_TOKENS,
    ):
        super().__init__("Chat", config)
        self.news_store = news_store
        self.paper_store = paper_store
        self.vector_store = vector_store
        self.max_history_tokens = max_history_tokens
        self._history: list[dict] = []
        self._fetch_client: httpx.AsyncClient | None = None
        self._total_trimmed = 0  # lifetime counter for observability

    def _get_fetch_client(self) -> httpx.AsyncClient:
        if self._fetch_client is None:
            self._fetch_client = httpx.AsyncClient(
                timeout=20.0,
                headers=FETCH_HEADERS,
                follow_redirects=True,
                trust_env=False,
            )
        return self._fetch_client

    async def aclose(self):
        if self._fetch_client is not None:
            await self._fetch_client.aclose()
            self._fetch_client = None
        await super().aclose()

    def _get_store(self, site_name: str = None):
        if site_name in ("deepmind_blog", "openai_blog"):
            return self.paper_store or self.news_store
        return self.news_store

    # ── context management ────────────────────────────────────────────

    def _trim_context(self) -> int:
        """Remove oldest exchanges until history fits in the token budget.

        Groups messages into exchanges (each starting with a ``user`` role).
        An exchange includes all subsequent assistant + tool messages until
        the next user message. This ensures tool-call sequences are never split.

        Returns the number of exchanges trimmed.
        """
        tokens = _messages_tokens(self._history)
        if tokens <= self.max_history_tokens:
            return 0

        # Partition history into exchange groups
        exchanges: list[list[dict]] = []
        current: list[dict] = []
        for msg in self._history:
            if msg["role"] == "user" and current:
                exchanges.append(current)
                current = []
            current.append(msg)
        if current:
            exchanges.append(current)

        if len(exchanges) <= MIN_EXCHANGES:
            return 0

        trimmed = 0
        while len(exchanges) > MIN_EXCHANGES:
            total = sum(_messages_tokens(ex) for ex in exchanges)
            if total <= self.max_history_tokens:
                break
            exchanges.pop(0)
            trimmed += 1

        if trimmed:
            self._history = [m for ex in exchanges for m in ex]
            self._total_trimmed += trimmed
            logger.info(
                "[ChatAgent] Trimmed %d old exchange(s); history: ~%d tokens, %d exchanges, %d lifetime trimmed",
                trimmed,
                _messages_tokens(self._history),
                len(exchanges),
                self._total_trimmed,
            )
        return trimmed

    def context_stats(self) -> dict:
        """Return current context usage for observability."""
        exchanges = 0
        for msg in self._history:
            if msg["role"] == "user":
                exchanges += 1
        return {
            "history_tokens": _messages_tokens(self._history),
            "exchanges": exchanges,
            "max_history_tokens": self.max_history_tokens,
            "lifetime_trimmed": self._total_trimmed,
        }

    # ── article fetching ─────────────────────────────────────────────

    async def _fetch_and_summarize(self, url: str, title: str = "") -> str:
        """Fetch an article URL, extract text, and summarize via LLM."""
        client = self._get_fetch_client()
        response = await client.get(url)
        response.raise_for_status()

        text = SCRIPT_STYLE_RE.sub(" ", response.text)
        soup = BeautifulSoup(text, "lxml")
        body = soup.get_text(separator=" ")
        body = WHITESPACE_RE.sub(" ", body).strip()

        if len(body) > 6000:
            body = body[:6000] + "…[内容已截断]"

        if len(body) < 100:
            return (
                f"文章内容过短（{len(body)} 字符），可能为动态加载页面，无法提取正文。"
            )

        title_hint = f"标题：「{title}」\n" if title else ""
        prompt = (
            f"{title_hint}请用 3-5 句中文摘要以下文章的核心内容，"
            f"突出关键信息和观点：\n\n{body}"
        )

        response = await self.async_client.chat.completions.create(
            model=self.llm_config.get("model", "glm-4-flash"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
            timeout=30.0,
        )
        return response.choices[0].message.content or "(摘要生成失败)"

    # ── tool execution ───────────────────────────────────────────────

    async def _execute_tool(self, name: str, args: dict) -> str:
        logger.info("[ChatAgent] Executing tool: %s(%s)", name, args)
        try:
            if name == "query_news":
                site = args.get("site_name")
                tag = args.get("tag")
                limit = args.get("limit", 10)
                store = self._get_store(site)
                items = store.query_items(site_name=site, tag=tag, limit=limit)
                if not items:
                    return "未找到匹配的条目。"
                lines = [f"共 {len(items)} 条结果："]
                for it in items[:limit]:
                    t = it.get("snapshot_time", "")[:10]
                    lines.append(
                        f"- [{it.get('tag', '无标签')}] {it.get('title', '无标题')[:60]} ({t})"
                    )
                return "\n".join(lines)

            if name == "get_stats":
                site = args.get("site_name", "")
                store = self._get_store(site)
                meta = store.get_metadata(site)
                runs = store.get_run_history(site, limit=5)
                if not meta:
                    return f"站点 {site} 暂无数据。"
                last_run = runs[0] if runs else {}
                return (
                    f"站点 {site} 概况：\n"
                    f"- 最近状态: {last_run.get('status', 'N/A')}\n"
                    f"- 最近条目数: {last_run.get('items_found', 0)}\n"
                    f"- 最近变更数: {last_run.get('changes_detected', 0)}\n"
                    f"- 标签分布: {json.dumps(meta.get('latest_tag_distribution', {}), ensure_ascii=False)}\n"
                    f"- 最近更新: {meta.get('updated_at', 'N/A')[:19]}"
                )

            if name == "search_semantic":
                if not self.vector_store:
                    return "语义搜索功能未启用（向量数据库未初始化）。"
                query = args.get("query", "")
                site = args.get("site_name")
                limit = args.get("limit", 5)
                results = self.vector_store.search(query, site_name=site, limit=limit)
                if not results:
                    return f"未找到与「{query}」相关的内容。"
                lines = [f"与「{query}」最相关的 {len(results)} 条结果："]
                for r in results:
                    lines.append(
                        f"- [{r.get('tag', '')}] {r.get('title', '')[:60]} "
                        f"({r.get('site_name', '')}, 相似度: {r.get('score', 0):.2f})"
                    )
                return "\n".join(lines)

            if name == "fetch_article":
                url = args.get("url", "")
                title = args.get("title", "")
                if not url:
                    return "未提供文章链接。"
                return await self._fetch_and_summarize(url, title)

            return f"未知工具: {name}"
        except httpx.HTTPStatusError as e:
            logger.warning(
                "[ChatAgent] fetch_article HTTP %d for %s",
                e.response.status_code,
                args.get("url", ""),
            )
            return f"抓取失败：HTTP {e.response.status_code}"
        except httpx.ConnectError:
            logger.warning(
                "[ChatAgent] fetch_article ConnectError for %s", args.get("url", "")
            )
            return "抓取失败：无法连接到目标网站（可能被屏蔽或网络不通）。"
        except Exception as e:
            logger.warning("[ChatAgent] Tool %s failed: %s", name, e)
            return f"工具执行失败: {e}"

    # ── chat ──────────────────────────────────────────────────────────

    async def chat(self, user_message: str) -> dict:
        """Process a user message and return assistant reply with tool call trace.

        Persists ALL messages (including tool_calls and tool results) to
        ``_history`` so the LLM retains full context across turns.  Trims
        oldest exchanges when the token budget is exceeded.
        """
        self._history.append({"role": "user", "content": user_message})

        # Build message list: system prompt + managed history
        system_msg = {"role": "system", "content": SYSTEM_PROMPT}
        messages = [system_msg] + self._history

        tool_calls_log: list[dict] = []
        tool_msg_indices: list[int] = []  # track newly appended messages in _history

        for _round in range(MAX_TOOL_ROUNDS + 1):
            response = await self.async_client.chat.completions.create(
                model=self.llm_config.get("model", "glm-4-flash"),
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
                tools=TOOLS,
                timeout=30.0,
            )
            choice = response.choices[0]
            msg = choice.message

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    fn = tc.function
                    args = json.loads(fn.arguments) if fn.arguments else {}
                    result_text = await self._execute_tool(fn.name, args)
                    tool_calls_log.append(
                        {"tool": fn.name, "args": args, "result": result_text[:200]}
                    )

                    assistant_msg = {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": fn.name,
                                    "arguments": fn.arguments,
                                },
                            }
                        ],
                    }
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    }

                    # Append to both working messages and persistent history
                    messages.append(assistant_msg)
                    messages.append(tool_msg)
                    self._history.append(assistant_msg)
                    self._history.append(tool_msg)
                    tool_msg_indices.extend([-2, -1])  # track for potential rollback
                continue  # next tool-calling round

            # Final assistant reply (no more tool calls)
            reply = msg.content or ""
            self._history.append({"role": "assistant", "content": reply})

            # Trim if over budget
            trimmed = self._trim_context()

            return {
                "reply": reply,
                "tool_calls": tool_calls_log,
                "context": self.context_stats(),
                "context_trimmed": trimmed,
            }

        # Max rounds exceeded — trim the incomplete tool chain from history
        reply = "抱歉，处理您的请求需要更多轮次，请简化提问。"
        self._history.append({"role": "assistant", "content": reply})
        return {
            "reply": reply,
            "tool_calls": tool_calls_log,
            "context": self.context_stats(),
            "context_trimmed": 0,
        }

    def clear_history(self):
        self._history.clear()
        self._total_trimmed = 0
        logger.info("[ChatAgent] History cleared")
