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
from pathlib import Path

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
    {
        "type": "function",
        "function": {
            "name": "my_preferences",
            "description": "查看系统根据你的历史对话行为推测的兴趣偏好和关注领域",
            "parameters": {"type": "object", "properties": {}, "required": []},
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

CHAT_HISTORY_FILE = Path("data/chat_history.json")
PREFERENCES_FILE = Path("data/user_preferences.json")
PREFERENCE_INFER_INTERVAL = 5  # run LLM inference every N exchanges

MAX_TOOL_ROUNDS = 3
MAX_HISTORY_TOKENS = (
    4000  # budget for _history only; system prompt + response use separate budget
)
MIN_EXCHANGES = 1  # always keep at least this many exchanges
COMPRESSION_THRESHOLD = 0.6  # compress when history exceeds 60% of budget
COMPRESSION_TARGET = 0.4  # compress the oldest ~40% of exchanges
MAX_TOOL_RESULTS = 5  # keep this many recent tool results; older ones truncated


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
        self._total_compressed = 0
        self._total_cleaned = 0
        self._preferences: dict = {}
        self._load_history()
        self._load_preferences()

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

    def _get_exchanges(self) -> list[list[dict]]:
        """Partition _history into exchange groups.

        Each exchange starts with a ``user`` message and includes all
        subsequent assistant + tool messages until the next user message.
        """
        exchanges: list[list[dict]] = []
        current: list[dict] = []
        for msg in self._history:
            if msg["role"] == "user" and current:
                exchanges.append(current)
                current = []
            current.append(msg)
        if current:
            exchanges.append(current)
        return exchanges

    async def _compress_exchanges(self, exchanges: list[list[dict]]) -> str:
        """Summarize a list of exchanges into a short Chinese paragraph."""
        lines = []
        for ex in exchanges:
            for m in ex:
                content = m.get("content", "")
                if (
                    isinstance(content, str)
                    and content
                    and m.get("role") in ("user", "assistant")
                ):
                    lines.append(f"[{m['role']}]: {content[:200]}")
        if not lines:
            return ""

        conversation = "\n".join(lines)
        prompt = (
            "请用 3-5 句中文摘要以下对话的关键信息"
            "（用户关注的话题、已查询的站点/标签、重要结论）：\n\n" + conversation
        )
        try:
            response = await self.async_client.chat.completions.create(
                model=self.llm_config.get("model", "glm-4-flash"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=256,
                timeout=20.0,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning("[ChatAgent] Compression summary failed: %s", e)
            return ""

    async def _maybe_compress(self):
        """Proactively compress oldest exchanges when token usage exceeds threshold."""
        tokens = _messages_tokens(self._history)
        if tokens <= self.max_history_tokens * COMPRESSION_THRESHOLD:
            return

        exchanges = self._get_exchanges()
        if len(exchanges) <= MIN_EXCHANGES + 1:
            return  # need at least 2 exchanges for meaningful compression

        # Compress oldest ~40% of exchanges, keeping at least MIN_EXCHANGES
        compress_count = max(1, int(len(exchanges) * COMPRESSION_TARGET))
        compress_count = min(compress_count, len(exchanges) - MIN_EXCHANGES)
        if compress_count <= 0:
            return

        to_compress = exchanges[:compress_count]
        keep = exchanges[compress_count:]

        summary = await self._compress_exchanges(to_compress)
        if not summary:
            return

        # Replace compressed exchanges with a synthetic summary message
        self._history = [{"role": "system", "content": f"[对话摘要] {summary}"}] + [
            m for ex in keep for m in ex
        ]
        self._total_compressed += 1
        logger.info(
            "[ChatAgent] Compressed %d exchange(s) into summary (%d chars); "
            "history: ~%d tokens, %d exchanges remaining",
            compress_count,
            len(summary),
            _messages_tokens(self._history),
            len(keep),
        )

    def _cleanup_old_tool_results(self):
        """Truncate old tool result contents, keeping the most recent N intact."""
        tool_indices = [
            i for i, m in enumerate(self._history) if m.get("role") == "tool"
        ]
        if len(tool_indices) <= MAX_TOOL_RESULTS:
            return

        cleaned = 0
        for idx in tool_indices[:-MAX_TOOL_RESULTS]:
            msg = self._history[idx]
            if len(msg.get("content", "")) > 30:
                tc_id = msg.get("tool_call_id", "unknown")
                msg["content"] = f"[已清除: 旧查询结果 — {tc_id}]"
                cleaned += 1

        if cleaned:
            self._total_cleaned += cleaned
            logger.info(
                "[ChatAgent] Cleaned %d old tool result(s); %d lifetime cleaned",
                cleaned,
                self._total_cleaned,
            )

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

        exchanges = self._get_exchanges()
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
            "lifetime_compressed": self._total_compressed,
            "lifetime_cleaned": self._total_cleaned,
        }

    # ── article fetching ─────────────────────────────────────────────

    async def _fetch_and_summarize(self, url: str, title: str = "") -> str:
        """Fetch an article URL, extract text, and summarize via LLM.

        Caches the summary to news_items.summary so repeated requests for the
        same URL skip re-fetching.
        """
        # Check cache first
        for store in (self.news_store, self.paper_store):
            if store:
                cached = store.get_item_summary(url)
                if cached:
                    logger.info("[ChatAgent] Article summary cache hit: %s", url[:60])
                    return cached

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
        summary = response.choices[0].message.content or "(摘要生成失败)"

        # Cache the summary
        for store in (self.news_store, self.paper_store):
            if store:
                try:
                    store.update_item_summary(url, summary)
                except Exception:
                    pass

        return summary

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

            if name == "my_preferences":
                return self._format_preferences()

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
        system_content = SYSTEM_PROMPT
        inferences = self._preferences.get("inferences", {})
        if inferences.get("summary"):
            system_content += (
                f"\n\n用户偏好参考（根据历史行为推断，仅供参考，不要刻意迎合）: "
                f"核心兴趣: {json.dumps(inferences.get('top_interests', []), ensure_ascii=False)}; "
                f"偏好概要: {inferences['summary']}"
            )
        system_msg = {"role": "system", "content": system_content}
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

            # Compress old exchanges (preserve info) → clean old tool results (save tokens) → trim (hard budget)
            await self._maybe_compress()
            self._cleanup_old_tool_results()
            trimmed = self._trim_context()
            self._save_history()

            # Collect behavior signals; trigger LLM inference if due
            if self._collect_behavior_signals():
                await self._infer_preferences()

            return {
                "reply": reply,
                "tool_calls": tool_calls_log,
                "context": self.context_stats(),
                "context_trimmed": trimmed,
            }

        # Max rounds exceeded — trim the incomplete tool chain from history
        reply = "抱歉，处理您的请求需要更多轮次，请简化提问。"
        self._history.append({"role": "assistant", "content": reply})
        self._save_history()
        self._collect_behavior_signals()  # collect signals even on partial success
        return {
            "reply": reply,
            "tool_calls": tool_calls_log,
            "context": self.context_stats(),
            "context_trimmed": 0,
        }

    # ── streaming chat (SSE) ──────────────────────────────────────────

    async def chat_stream(self, user_message: str):
        """Async generator yielding SSE events for streaming chat.

        Tool-calling rounds use non-streaming (need full JSON to parse tool_calls).
        Final reply tokens are streamed one at a time.
        """
        self._history.append({"role": "user", "content": user_message})

        system_content = SYSTEM_PROMPT
        inferences = self._preferences.get("inferences", {})
        if inferences.get("summary"):
            system_content += (
                f"\n\n用户偏好参考（根据历史行为推断，仅供参考，不要刻意迎合）: "
                f"核心兴趣: {json.dumps(inferences.get('top_interests', []), ensure_ascii=False)}; "
                f"偏好概要: {inferences['summary']}"
            )
        system_msg = {"role": "system", "content": system_content}
        messages = [system_msg] + self._history

        tool_calls_log: list[dict] = []

        yield self._sse("status", "正在分析...")

        for _round in range(MAX_TOOL_ROUNDS + 1):
            # Tool-calling rounds: non-streaming (need full JSON)
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
                    yield self._sse("tool_call", {"tool": fn.name, "args": args})
                    result_text = await self._execute_tool(fn.name, args)
                    tool_calls_log.append(
                        {"tool": fn.name, "args": args, "result": result_text[:200]}
                    )
                    yield self._sse("tool_result", {"result": result_text[:200]})

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
                    messages.append(assistant_msg)
                    messages.append(tool_msg)
                    self._history.append(assistant_msg)
                    self._history.append(tool_msg)
                continue  # next tool round

            # Final reply: streaming
            yield self._sse("status", "正在生成回复...")
            model = self.llm_config.get("model", "glm-4-flash")

            # Build messages with just the system prompt + history for streaming
            reply_parts = []
            stream = await self.async_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
                timeout=30.0,
                stream=True,
            )
            total_tokens = 0
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    reply_parts.append(delta.content)
                    yield self._sse("token", delta.content)
                if chunk.usage and chunk.usage.total_tokens:
                    total_tokens = chunk.usage.total_tokens
            self._last_tokens = total_tokens

            reply = "".join(reply_parts)
            self._history.append({"role": "assistant", "content": reply})

            # Compress / clean / trim
            await self._maybe_compress()
            self._cleanup_old_tool_results()
            trimmed = self._trim_context()
            self._save_history()

            if self._collect_behavior_signals():
                await self._infer_preferences()

            ctx = self.context_stats()
            yield self._sse("tool_calls", tool_calls_log)
            yield self._sse(
                "context",
                {
                    "history_tokens": ctx["history_tokens"],
                    "exchanges": ctx["exchanges"],
                },
            )
            yield self._sse("done", {"trimmed": trimmed})
            return

        # Max rounds exceeded
        reply = "抱歉，处理您的请求需要更多轮次，请简化提问。"
        self._history.append({"role": "assistant", "content": reply})
        self._save_history()
        self._collect_behavior_signals()
        yield self._sse("token", reply)
        yield self._sse("done", {})
        return

    @staticmethod
    def _sse(event: str, data) -> str:
        """Format an SSE event string."""
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n"

    # ── persistence ─────────────────────────────────────────────────────

    def _load_history(self):
        """Load chat history from JSON file. Graceful on missing/corrupt file."""
        try:
            if CHAT_HISTORY_FILE.exists():
                data = json.loads(CHAT_HISTORY_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._history = data
                    logger.info(
                        "[ChatAgent] Loaded %d messages from %s",
                        len(self._history),
                        CHAT_HISTORY_FILE,
                    )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[ChatAgent] Failed to load chat history: %s", e)

    def _save_history(self):
        """Persist chat history to JSON file."""
        try:
            CHAT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            CHAT_HISTORY_FILE.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("[ChatAgent] Failed to save chat history: %s", e)

    # ── user preference analysis ────────────────────────────────────────

    def _load_preferences(self):
        """Load user preference profile from JSON file."""
        try:
            if PREFERENCES_FILE.exists():
                self._preferences = json.loads(
                    PREFERENCES_FILE.read_text(encoding="utf-8")
                )
                logger.info(
                    "[ChatAgent] Loaded user preferences (%d exchanges tracked)",
                    self._preferences.get("signals", {}).get("total_exchanges", 0),
                )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[ChatAgent] Failed to load preferences: %s", e)
            self._preferences = {}

    def _save_preferences(self):
        """Persist user preference profile to JSON file."""
        try:
            PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
            PREFERENCES_FILE.write_text(
                json.dumps(self._preferences, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("[ChatAgent] Failed to save preferences: %s", e)

    def _collect_behavior_signals(self):
        """Extract heuristic signals from the latest exchange's tool calls."""
        signals = self._preferences.setdefault("signals", {})
        signals.setdefault("queried_sites", {})
        signals.setdefault("queried_tags", {})
        signals.setdefault("used_tools", {})
        signals.setdefault("searched_topics", [])
        signals.setdefault("fetched_urls", [])
        signals.setdefault("total_exchanges", 0)

        # Scan the last exchange for tool_call messages
        tool_calls_seen = 0
        for msg in reversed(self._history):
            if msg["role"] == "user":
                break  # reached the start of the current exchange
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    tool_name = fn["name"]
                    try:
                        tool_args = json.loads(fn["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}

                    signals["used_tools"][tool_name] = (
                        signals["used_tools"].get(tool_name, 0) + 1
                    )

                    site = tool_args.get("site_name")
                    if site and tool_name in ("query_news", "get_stats"):
                        signals["queried_sites"][site] = (
                            signals["queried_sites"].get(site, 0) + 1
                        )

                    tag = tool_args.get("tag")
                    if tag and tool_name == "query_news":
                        signals["queried_tags"][tag] = (
                            signals["queried_tags"].get(tag, 0) + 1
                        )

                    if tool_name == "search_semantic":
                        query = tool_args.get("query", "")
                        if query:
                            topics = signals["searched_topics"]
                            topics.append(query)
                            # Keep only last 20
                            signals["searched_topics"] = topics[-20:]

                    if tool_name == "fetch_article":
                        url = tool_args.get("url", "")
                        if url and url not in signals["fetched_urls"]:
                            signals["fetched_urls"].append(url)
                            signals["fetched_urls"] = signals["fetched_urls"][-20:]

                    tool_calls_seen += 1

        signals["total_exchanges"] += 1
        self._save_preferences()

        # Trigger LLM inference periodically
        if signals["total_exchanges"] % PREFERENCE_INFER_INTERVAL == 0:
            logger.info(
                "[ChatAgent] Triggering preference inference at %d exchanges",
                signals["total_exchanges"],
            )
            return True  # signal that inference is due
        return False

    async def _infer_preferences(self):
        """Use LLM to analyze behavior signals and infer user preferences."""
        signals = self._preferences.get("signals", {})
        existing = self._preferences.get("inferences", {})

        prompt = f"""你是用户偏好分析专家。根据以下用户行为信号，推断用户的核心兴趣和偏好。

行为信号：
- 查询站点频率: {json.dumps(signals.get("queried_sites", {}), ensure_ascii=False)}
- 查询标签频率: {json.dumps(signals.get("queried_tags", {}), ensure_ascii=False)}
- 使用工具频率: {json.dumps(signals.get("used_tools", {}), ensure_ascii=False)}
- 语义搜索主题: {json.dumps(signals.get("searched_topics", []), ensure_ascii=False)}
- 抓取文章数: {len(signals.get("fetched_urls", []))}
- 总对话轮次: {signals.get("total_exchanges", 0)}

已有偏好推断: {json.dumps(existing, ensure_ascii=False) if existing else "无"}

请综合以上信号分析用户的核心兴趣偏好，输出 JSON：
{{"summary": "用一两句话总结用户整体偏好", "top_interests": ["兴趣1", "兴趣2", ...], "preferred_sources": ["来源1", ...], "behavior_pattern": "用户行为模式简述"}}"""

        try:
            response = await self.call_llm_async(
                system_prompt="你是用户行为分析专家。输出严格的 JSON，不要额外文字。",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=256,
            )
            inferences = self.parse_json_response(response)
            if isinstance(inferences, list):
                inferences = inferences[0] if inferences else {}
            if isinstance(inferences, dict):
                inferences["inferred_at"] = (
                    __import__("datetime").datetime.now().isoformat()
                )
                inferences["based_on_exchanges"] = signals.get("total_exchanges", 0)
                self._preferences["inferences"] = inferences
                self._save_preferences()
                logger.info(
                    "[ChatAgent] Updated user preference inferences: %s",
                    inferences.get("summary", ""),
                )
        except Exception as e:
            logger.warning("[ChatAgent] Preference inference failed: %s", e)

    def _format_preferences(self) -> str:
        """Format preferences for my_preferences tool output."""
        inferences = self._preferences.get("inferences", {})
        signals = self._preferences.get("signals", {})

        if not inferences and not signals.get("total_exchanges"):
            return "暂无偏好数据。多和我对话后，我会自动分析你的兴趣偏好。"

        parts = []
        if inferences.get("summary"):
            parts.append(f"偏好概要: {inferences['summary']}")
        if inferences.get("top_interests"):
            parts.append(f"核心兴趣: {', '.join(inferences['top_interests'])}")
        if inferences.get("preferred_sources"):
            parts.append(f"偏好来源: {', '.join(inferences['preferred_sources'])}")
        if signals.get("queried_tags"):
            top_tags = sorted(
                signals["queried_tags"].items(), key=lambda x: x[1], reverse=True
            )[:5]
            parts.append(f"常查标签: {', '.join(f'{t}({c}次)' for t, c in top_tags)}")
        parts.append(
            f"统计: 共 {signals.get('total_exchanges', 0)} 轮对话, "
            f"使用 {len(signals.get('queried_sites', {}))} 个站点"
        )
        return "\n".join(parts)

    def clear_history(self):
        self._history.clear()
        self._total_trimmed = 0
        self._total_compressed = 0
        self._total_cleaned = 0
        self._save_history()
        logger.info("[ChatAgent] History cleared")
