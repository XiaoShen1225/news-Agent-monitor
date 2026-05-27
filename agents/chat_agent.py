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
import uuid
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

# ── Valid site names ───────────────────────────────────────────────────
VALID_SITES = ["baidu_news", "sina_news", "deepmind_blog", "openai_blog"]

# ── Tool definitions ───────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_news",
            "description": (
                "查询数据库中存储的新闻/论文条目。"
                "【使用场景】用户询问'最近有什么新闻'、'某类新闻'、'包含某关键词的新闻'时使用。"
                "【参数提示】site_name限定站点；tag按标签筛选（如科技/财经/国际）；"
                "keyword用于标题关键词模糊搜索；limit控制返回数量，默认10。"
                "【注意】如果用户想看具体文章内容，应使用 fetch_article 而非此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "site_name": {
                        "type": "string",
                        "enum": VALID_SITES,
                        "description": "站点名称。不传查询全部。baidu_news（百度新闻）、sina_news（新浪新闻）、deepmind_blog（DeepMind博客）、openai_blog（OpenAI博客）",
                    },
                    "tag": {
                        "type": "string",
                        "maxLength": 20,
                        "description": "标签筛选。新闻站点常见标签：科技, 要闻, 财经, 军事, 娱乐, 国内, 国际, 体育；论文站点固定：AI研究",
                    },
                    "keyword": {
                        "type": "string",
                        "maxLength": 100,
                        "description": "标题关键词搜索（SQL LIKE模糊匹配），例如 'GPT'、'华为'、'芯片'。适合用户询问特定新闻时使用",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "返回条数上限，默认10，最大50",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": (
                "获取指定站点的最新运行统计（最近状态、抓取条目数、变更数、标签分布、更新时间）。"
                "【使用场景】用户询问'某站点运行情况'、'最近有没有新数据'、'监控状态如何'时使用。"
                "【参数提示】site_name为必填，可选值见enum列表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "site_name": {
                        "type": "string",
                        "enum": VALID_SITES,
                        "description": "站点名称，必填。baidu_news / sina_news / deepmind_blog / openai_blog",
                    }
                },
                "required": ["site_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_semantic",
            "description": (
                "语义搜索已有新闻/论文标题，按语义相似度排序。"
                "【使用场景】用户用自然语言描述想找的内容（如'关于人工智能突破的文章'），不确定具体关键词时使用。"
                "【与query_news的区别】query_news用关键词精确匹配标题；search_semantic用语义理解，能匹配意思相近的内容。"
                "【参数提示】query为必填，用自然语言描述即可；limit默认5，最大20。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "自然语言搜索描述，例如'最近关于人工智能突破的新闻报道'",
                    },
                    "site_name": {
                        "type": "string",
                        "enum": VALID_SITES,
                        "description": "限定站点，不传搜全部",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "返回结果数，默认5，最大20",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_article",
            "description": (
                "抓取指定URL的网页正文内容并用AI生成中文摘要。"
                "【使用场景】用户想了解某篇新闻/文章的具体内容时使用（通常在query_news或search_semantic返回结果后）。"
                "【注意】此工具需要网络请求，耗时较长（5-15秒），仅当用户明确要求查看内容时才调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "format": "uri",
                        "maxLength": 2048,
                        "description": "文章链接URL，必须是完整的http/https地址",
                    },
                    "title": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "文章标题（可选），帮助生成更准确的摘要",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_preferences",
            "description": (
                "查看系统根据你的历史对话行为推测的兴趣偏好和关注领域。"
                "【使用场景】用户询问'我喜欢什么'、'你了解我的偏好吗'、'我经常看什么内容'时使用。"
                "【注意】偏好分析需要至少几轮对话数据，初期可能返回'暂无偏好数据'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_preference",
            "description": (
                "更新用户的显式偏好（喜欢或不喜欢某类内容）。"
                "【使用场景】用户明确表达'我喜欢/不喜欢某类新闻'、'多推/少推某类'、'对XX不感兴趣'时使用。"
                "【参数提示】interest为偏好关键词；action为like（喜欢）或dislike（不喜欢）；confidence为确信度0-1（默认0.9）"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "interest": {
                        "type": "string",
                        "maxLength": 50,
                        "description": "偏好关键词，如'科技'、'体育'、'国际'、'AI研究'",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["like", "dislike"],
                        "description": "like（喜欢此类内容）/ dislike（不喜欢此类内容）",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "确信度，默认0.9。用户明确表达时设为0.9+，暗示时设为0.5-0.7",
                    },
                },
                "required": ["interest", "action"],
                "additionalProperties": False,
            },
        },
    },
]

SYSTEM_PROMPT = """# 身份与角色

你是 News Agent Monitor 的智能对话助手 "NewsGPT"，帮助用户查询和分析新闻/论文监控数据。
你只负责回答与新闻监控、论文追踪、数据查询相关的问题。

# 核心知识

本系统自动监控多个新闻和论文网站，定时抓取、提取、对比变化并生成可视化图表。

## 数据存储
- SQLite 数据库：`data/monitor.db`（新闻）+ `data/papers.db`（论文）
- snapshots 表：抓取的条目（title, url, tag, site_name, content_hash, snapshot_time）
- run_history 表：每次 pipeline 运行记录（status, items_found, changes_detected, duration）
- metadata 表：站点元信息（标签分布, 更新时间, 运行统计）

## Pipeline 流程
Fetch（httpx/Playwright 抓取网页）→ Parse（LLM 提取新闻+分类打标签）→ Analyze（对比历史快照计算 diff + LLM 生成变更摘要）→ Visualize（matplotlib + ECharts 生成图表）→ Notify（可选：钉钉/企业微信/邮件推送）

## 监控站点
| 站点 | 类型 | 抓取方式 | 频率 | 常见标签 |
|------|------|----------|------|----------|
| baidu_news | 新闻 | Playwright 浏览器 | 60 min | 科技, 要闻, 财经, 军事, 娱乐, 国内, 国际, 体育 |
| sina_news | 新闻 | httpx 静态 | 120 min | 国际, 体育, 社会, 财经, 国内, 军事, 汽车, 其他 |
| deepmind_blog | 论文 | RSS feed | 360 min | AI研究 |
| openai_blog | 论文 | RSS feed | 360 min | AI研究 |

## 重要说明
- deepmind.google 在国内被 GFW 阻断（TLS 层），deepmind_blog 大概率抓取失败，非系统故障
- 新闻站点（baidu_news, sina_news）的标签由 LLM 自动分类，论文站点标签固定为 "AI研究"
- 变更检测通过 content_hash 对比，相同标题+URL 内容变化视为 modified

# 工具选择策略

在回答之前，先判断是否需要调用工具。以下是决策表：

| 用户意图 | 使用的工具 | 示例问题 |
|----------|-----------|----------|
| 查新闻/找文章 | query_news | "最近有什么科技新闻？""有没有关于芯片的新闻？" |
| 看站点运行状态 | get_stats | "百度新闻运行正常吗？""最近抓取了多少数据？" |
| 自然语言搜内容 | search_semantic | "关于人工智能突破的文章""和环保相关的内容" |
| 看文章具体内容 | fetch_article | "这篇文章讲了什么？""帮我总结一下这篇新闻" |
| 了解自己的偏好 | my_preferences | "我喜欢什么类型的新闻？""你了解我的兴趣吗？" |
| 问项目本身的问题 | 不调用工具 | "有哪些监控站点？""系统是怎么工作的？" |

**规则**：
- 一次只调用一个工具，等待结果后再决定下一步
- 最多调用 3 轮工具；如果 3 轮后仍无法回答，如实说明
- 如果用户问题需要多个工具配合，先查列表（query_news/search_semantic），再查详情（fetch_article）

# 思考流程

收到问题后按以下步骤处理：

1. **理解意图** — 用户到底想知道什么？查新闻、看统计、搜文章、还是了解系统？
2. **选择工具** — 根据上方的决策表，确定需要哪个工具（或不需要工具）
3. **构造参数** — 从用户问题中提取关键词、站点名、标签等参数
4. **执行查询** — 调用工具获取真实数据
5. **整合回答** — 基于工具返回的数据，用中文给出简洁准确的回答

# 回答规范

- 使用中文回复，简洁准确（通常 3-6 句）
- **所有数据必须来自工具查询结果**，绝对不要编造任何新闻标题、统计数据或摘要内容
- 工具返回空结果时，如实告知用户并建议调整筛选条件（如换关键词、放宽站点限制）
- 回答中可以引用具体数据（标题、时间、数量），增强可信度
- 如果连续两轮工具返回空结果，应如实说明，不要反复尝试不同工具

# 拒绝规则

以下情况必须拒绝：

| 请求类型 | 拒绝方式 |
|----------|----------|
| 要求操作/修改系统（删除数据、重启服务、改配置） | "抱歉，我只能查询数据，不能操作系统。如需管理操作，请使用命令行。" |
| 询问非新闻监控的话题（天气、股票、闲聊） | "我是新闻监控助手，只能回答与新闻/论文数据相关的问题。有什么监控数据方面的疑问我可以帮你？" |
| 要求编造或虚构信息 | 拒绝并说明你只基于真实数据库中的数据回答 |

# 输出格式

- 简单数据查询 → 自然语言回复
- 展示多条新闻 → 简短的列表格式（`- 标题（日期）`）
- 展示统计数据 → 分项格式（`- 指标：数值`）
- 不要输出 JSON、代码块或 Markdown 表格，除非用户明确要求
- 不要在回复中输出你的思考步骤（如"步骤1、步骤2"），直接给出结果"""

CHAT_HISTORY_FILE = Path("data/chat_history.json")
PREFERENCES_FILE = Path("data/user_preferences.json")
PREFERENCE_LITE_INTERVAL = 2  # run lightweight inference every N exchanges
PREFERENCE_FULL_INTERVAL = 5  # run full inference every N exchanges
SIGNAL_HALFLIFE_DAYS = 14  # signal weight halves after this many days

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
        max_history_tokens: int | None = None,
    ):
        super().__init__("Chat", config)
        self.news_store = news_store
        self.paper_store = paper_store
        self.vector_store = vector_store
        # Read chat settings from config, with module-level constants as fallback
        chat_cfg = config.get("chat", {})
        self.max_history_tokens = max_history_tokens or chat_cfg.get(
            "max_history_tokens", MAX_HISTORY_TOKENS
        )
        self.max_tool_rounds = chat_cfg.get("max_tool_rounds", MAX_TOOL_ROUNDS)
        self.min_exchanges = chat_cfg.get("min_exchanges", MIN_EXCHANGES)
        self.compression_threshold = chat_cfg.get(
            "compression_threshold", COMPRESSION_THRESHOLD
        )
        self.compression_target = chat_cfg.get("compression_target", COMPRESSION_TARGET)
        self.max_tool_results = chat_cfg.get("max_tool_results", MAX_TOOL_RESULTS)
        self.pref_lite_interval = chat_cfg.get(
            "preference_lite_interval", PREFERENCE_LITE_INTERVAL
        )
        self.pref_full_interval = chat_cfg.get(
            "preference_full_interval", PREFERENCE_FULL_INTERVAL
        )
        self.signal_halflife_days = chat_cfg.get(
            "signal_halflife_days", SIGNAL_HALFLIFE_DAYS
        )
        self._fetch_client: httpx.AsyncClient | None = None
        self._preferences: dict = {}
        # Session support — each session isolates conversation history + stats
        self._sessions: dict[str, dict] = {}
        self._current_session_id: str | None = None
        # Default session (backwards-compat when no session_id provided)
        self._default_session = self._new_session_data()
        self._load_history()
        self._load_preferences()

    @staticmethod
    def _new_session_data() -> dict:
        return {
            "history": [],
            "total_trimmed": 0,
            "total_compressed": 0,
            "total_cleaned": 0,
            "created_at": ChatAgent._now_iso(),
        }

    def _get_session(self, session_id: str | None) -> str:
        """Resolve session_id; create if new. Returns the session id."""
        if session_id and session_id in self._sessions:
            return session_id
        sid = session_id or str(uuid.uuid4())
        if sid not in self._sessions:
            self._sessions[sid] = self._new_session_data()
            logger.info("[ChatAgent] New session: %s", sid[:8])
        return sid

    def _activate_session(self, session_id: str | None) -> str:
        """Set the given session as active; return its id."""
        sid = self._get_session(session_id)
        self._current_session_id = sid
        return sid

    def _active(self) -> dict:
        """Return the currently active session data dict."""
        if self._current_session_id and self._current_session_id in self._sessions:
            return self._sessions[self._current_session_id]
        return self._default_session

    # ── Properties that delegate to the active session ──────────────

    @property
    def _history(self) -> list[dict]:
        return self._active()["history"]

    @_history.setter
    def _history(self, value):
        self._active()["history"] = value

    @property
    def _total_trimmed(self) -> int:
        return self._active()["total_trimmed"]

    @_total_trimmed.setter
    def _total_trimmed(self, value):
        self._active()["total_trimmed"] = value

    @property
    def _total_compressed(self) -> int:
        return self._active()["total_compressed"]

    @_total_compressed.setter
    def _total_compressed(self, value):
        self._active()["total_compressed"] = value

    @property
    def _total_cleaned(self) -> int:
        return self._active()["total_cleaned"]

    @_total_cleaned.setter
    def _total_cleaned(self, value):
        self._active()["total_cleaned"] = value

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
        if tokens <= self.max_history_tokens * self.compression_threshold:
            return

        exchanges = self._get_exchanges()
        if len(exchanges) <= self.min_exchanges + 1:
            return  # need at least 2 exchanges for meaningful compression

        # Compress oldest ~40% of exchanges, keeping at least self.min_exchanges
        compress_count = max(1, int(len(exchanges) * self.compression_target))
        compress_count = min(compress_count, len(exchanges) - self.min_exchanges)
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
        if len(tool_indices) <= self.max_tool_results:
            return

        cleaned = 0
        for idx in tool_indices[: -self.max_tool_results]:
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
        if len(exchanges) <= self.min_exchanges:
            return 0

        trimmed = 0
        while len(exchanges) > self.min_exchanges:
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

        # Validate tool arguments before execution
        arg_error = self._validate_tool_args(name, args)
        if arg_error:
            return arg_error

        try:
            if name == "query_news":
                site = args.get("site_name")
                tag = args.get("tag")
                keyword = args.get("keyword")
                limit = args.get("limit", 10)
                store = self._get_store(site)
                items = store.query_items(
                    site_name=site, tag=tag, keyword=keyword, limit=limit
                )
                if not items:
                    return (
                        "[查询结果] 未找到匹配的条目。\n"
                        "建议尝试：1) 扩大关键词范围 2) 不限定站点 3) 减少标签筛选条件"
                    )

                # Preference-based sorting when no explicit tag/keyword filter
                boost_tags = []
                if not tag and not keyword:
                    overrides = self._preferences.get("explicit_overrides", {})
                    inferences = self._preferences.get("inferences", {})
                    conf_map = inferences.get("interest_confidence", {})
                    # Collect liked tags from explicit overrides + high-confidence interests
                    for k, v in overrides.items():
                        if v.get("action") == "like":
                            boost_tags.append(k)
                    for interest in inferences.get("top_interests", []):
                        if (
                            conf_map.get(interest, 0) >= 0.6
                            and interest not in boost_tags
                        ):
                            boost_tags.append(interest)
                    # Collect disliked tags to deprioritize
                    hide_tags = {
                        k for k, v in overrides.items() if v.get("action") == "dislike"
                    }

                if boost_tags or hide_tags:

                    def _pref_score(item: dict) -> float:
                        item_tag = item.get("tag", "")
                        item_title = item.get("title", "")
                        score = 0.0
                        for bt in boost_tags:
                            if bt in item_tag or bt in item_title:
                                score += 2.0
                        for ht in hide_tags:
                            if ht in item_tag or ht in item_title:
                                score -= 10.0
                        return score

                    items = sorted(items, key=_pref_score, reverse=True)
                    boosted = ", ".join(boost_tags[:3]) if boost_tags else ""
                    hint = (
                        f"（已根据你的偏好优先展示「{boosted}」相关内容）"
                        if boosted
                        else ""
                    )
                    lines = [f"[查询结果] 共找到 {len(items)} 条记录{hint}："]
                else:
                    lines = [f"[查询结果] 共找到 {len(items)} 条匹配记录："]

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
                    return f"[站点统计] {site} 暂无数据。可能是尚未完成首次抓取。"
                last_run = runs[0] if runs else {}
                return (
                    f"[站点统计 - {site}]\n"
                    f"- 最近运行状态: {last_run.get('status', 'N/A')}\n"
                    f"- 最近条目数: {last_run.get('items_found', 0)}\n"
                    f"- 最近变更数: {last_run.get('changes_detected', 0)}\n"
                    f"- 标签分布: {json.dumps(meta.get('latest_tag_distribution', {}), ensure_ascii=False)}\n"
                    f"- 最近更新: {meta.get('updated_at', 'N/A')[:19]}\n"
                    f"[提示] 可使用 query_news 工具进一步查看该站点的具体新闻条目。"
                )

            if name == "search_semantic":
                if not self.vector_store:
                    return (
                        "[语义搜索] 语义搜索功能未启用（向量数据库未初始化）。\n"
                        "建议：使用 query_news 工具通过关键词进行搜索。"
                    )
                query = args.get("query", "")
                site = args.get("site_name")
                limit = args.get("limit", 5)
                results = self.vector_store.search(query, site_name=site, limit=limit)
                if not results:
                    return (
                        f"[语义搜索] 未找到与「{query}」语义相关的内容。\n"
                        "建议尝试：1) 使用更通用的描述词 2) 用 query_news 进行关键词匹配搜索"
                    )
                lines = [
                    f"[语义搜索] 与「{query}」最相关的 {len(results)} 条结果（按相似度排序）："
                ]
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
                    return "[参数错误] 未提供文章链接。"
                summary = await self._fetch_and_summarize(url, title)
                return f"[文章摘要]\n{summary}"

            if name == "my_preferences":
                prefs = self._format_preferences()
                return f"[偏好分析]\n{prefs}"

            if name == "update_preference":
                interest = args["interest"]
                action = args["action"]
                conf = args.get("confidence", 0.9)
                overrides = self._preferences.setdefault("explicit_overrides", {})
                overrides[interest] = {
                    "action": action,
                    "confidence": conf,
                    "updated_at": self._now_iso(),
                }
                self._save_preferences()
                emoji = "已记录喜欢" if action == "like" else "已记录不喜欢"
                return (
                    f"[偏好更新] {emoji}「{interest}」"
                    f"（确信度: {conf:.0%}）。后续查询将据此调整结果排序。"
                )

            return f"[工具错误] 未知工具: {name}"

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            logger.warning(
                "[ChatAgent] fetch_article HTTP %d for %s",
                status,
                args.get("url", ""),
            )
            if status == 403:
                hint = "该网站可能屏蔽了自动抓取，建议用户手动访问原文。"
            elif status == 404:
                hint = "页面不存在，请检查URL是否正确。"
            elif status >= 500:
                hint = "目标网站服务器暂时不可用，建议稍后重试。"
            else:
                hint = f"HTTP {status}错误，请稍后重试。"
            return f"[抓取失败 - HTTP {status}] {hint}"

        except httpx.ConnectError:
            logger.warning(
                "[ChatAgent] fetch_article ConnectError for %s", args.get("url", "")
            )
            return (
                "[抓取失败 - 网络连接错误] 无法连接到目标网站。\n"
                "可能原因：1) 网站被GFW屏蔽（如deepmind.google） 2) 网站需要特殊网络环境 3) URL已失效"
            )

        except Exception as e:
            logger.warning("[ChatAgent] Tool %s failed: %s", name, e)
            return f"[工具异常 - {type(e).__name__}] 执行 {name} 时发生意外错误。建议简化查询条件或稍后重试。"

    def _validate_tool_args(self, name: str, args: dict) -> str | None:
        """Validate tool arguments. Returns error message or None if valid."""
        if name == "fetch_article":
            url = args.get("url", "")
            if url and not (url.startswith("http://") or url.startswith("https://")):
                return "[参数错误] URL必须以 http:// 或 https:// 开头。"
            if len(url) > 2048:
                return "[参数错误] URL过长（超过2048字符）。"
        if name == "query_news":
            site = args.get("site_name", "")
            if site and site not in VALID_SITES:
                return (
                    f"[参数提示] 未知站点 '{site}'。"
                    f"有效站点: {', '.join(VALID_SITES)}。已忽略此筛选条件，查询全部站点。"
                )
        if name == "get_stats":
            site = args.get("site_name", "")
            if site and site not in VALID_SITES:
                return (
                    f"[参数错误] 未知站点 '{site}'。"
                    f"有效站点: {', '.join(VALID_SITES)}。请重新指定。"
                )
        return None

    # ── chat ──────────────────────────────────────────────────────────

    # ── Input validation ──────────────────────────────────────────────

    def _validate_input(self, message: str) -> str | None:
        """Validate user input before processing. Returns rejection reason or None."""
        msg = message.strip()
        if not msg:
            return "请输入消息内容。"
        if len(msg) > 2000:
            return "消息过长（超过2000字符），请简化你的问题。"

        # Block obviously dangerous operation requests
        import re as _re

        blocked = [
            (
                r"(删除|清空|drop|delete|truncate)\s*(数据库|database|db|表|table)",
                "我只能查询数据，不能删除或修改数据库。",
            ),
            (
                r"(重启|restart|shutdown)\s*(服务|系统|server|system)",
                "我只能查询数据，不能控制系统运行。",
            ),
            (
                r"(修改|改|change|update)\s*(配置|config|设置|密码|password)",
                "我只能查询数据，不能修改系统配置。",
            ),
        ]
        for pattern, reason in blocked:
            if _re.search(pattern, msg, _re.IGNORECASE):
                return f"抱歉，{reason}如需管理操作，请使用命令行工具。"

        # Block prompt injection attempts
        injection_markers = [
            "ignore previous instructions",
            "ignore all previous",
            "disregard your system prompt",
            "你是一个",
            "你现在是",
            "忘记你的系统提示",
        ]
        for marker in injection_markers:
            if marker.lower() in msg.lower():
                logger.warning(
                    "[ChatAgent] Possible prompt injection attempt, rejecting"
                )
                return "抱歉，无法处理此请求。"

        return None

    # ── chat ──────────────────────────────────────────────────────────

    async def chat(self, user_message: str, session_id: str | None = None) -> dict:
        """Process a user message and return assistant reply with tool call trace.

        Persists ALL messages (including tool_calls and tool results) to
        ``_history`` so the LLM retains full context across turns.  Trims
        oldest exchanges when the token budget is exceeded.
        """
        sid = self._activate_session(session_id)
        rejection = self._validate_input(user_message)
        if rejection:
            self._history.append({"role": "assistant", "content": rejection})
            self._save_history()
            return {
                "reply": rejection,
                "tool_calls": [],
                "context": self.context_stats(),
                "context_trimmed": 0,
                "rejected": True,
                "session_id": sid,
            }

        self._history.append({"role": "user", "content": user_message})

        # Build message list: system prompt + managed history
        system_content = SYSTEM_PROMPT
        inferences = self._preferences.get("inferences", {})
        overrides = self._preferences.get("explicit_overrides", {})
        if inferences.get("summary") or overrides:
            system_content += (
                "\n\n用户偏好参考（根据历史行为推断，仅供参考，不要刻意迎合）:"
            )
            if overrides:
                likes = [k for k, v in overrides.items() if v.get("action") == "like"]
                dislikes = [
                    k for k, v in overrides.items() if v.get("action") == "dislike"
                ]
                if likes:
                    system_content += (
                        f" 用户明确喜欢: {json.dumps(likes, ensure_ascii=False)};"
                    )
                if dislikes:
                    system_content += (
                        f" 用户明确不喜欢: {json.dumps(dislikes, ensure_ascii=False)};"
                    )
            if inferences.get("top_interests"):
                system_content += f" 核心兴趣: {json.dumps(inferences.get('top_interests', []), ensure_ascii=False)};"
            if inferences.get("summary"):
                system_content += f" 偏好概要: {inferences['summary']}"
        system_msg = {"role": "system", "content": system_content}
        messages = [system_msg] + self._history

        tool_calls_log: list[dict] = []
        tool_msg_indices: list[int] = []  # track newly appended messages in _history

        for _round in range(self.max_tool_rounds + 1):
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
            level = self._collect_behavior_signals()
            if level == "full":
                await self._infer_preferences("full")
            elif level == "lite":
                await self._infer_preferences("lite")

            return {
                "reply": reply,
                "tool_calls": tool_calls_log,
                "context": self.context_stats(),
                "context_trimmed": trimmed,
                "session_id": sid,
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
            "session_id": sid,
        }

    # ── streaming chat (SSE) ──────────────────────────────────────────

    async def chat_stream(self, user_message: str, session_id: str | None = None):
        """Async generator yielding SSE events for streaming chat.

        Tool-calling rounds use non-streaming (need full JSON to parse tool_calls).
        Final reply tokens are streamed one at a time.
        """
        sid = self._activate_session(session_id)
        rejection = self._validate_input(user_message)
        if rejection:
            self._history.append({"role": "assistant", "content": rejection})
            self._save_history()
            yield self._sse("token", rejection)
            yield self._sse("done", {"rejected": True, "session_id": sid})
            return

        self._history.append({"role": "user", "content": user_message})

        system_content = SYSTEM_PROMPT
        inferences = self._preferences.get("inferences", {})
        overrides = self._preferences.get("explicit_overrides", {})
        if inferences.get("summary") or overrides:
            system_content += (
                "\n\n用户偏好参考（根据历史行为推断，仅供参考，不要刻意迎合）:"
            )
            if overrides:
                likes = [k for k, v in overrides.items() if v.get("action") == "like"]
                dislikes = [
                    k for k, v in overrides.items() if v.get("action") == "dislike"
                ]
                if likes:
                    system_content += (
                        f" 用户明确喜欢: {json.dumps(likes, ensure_ascii=False)};"
                    )
                if dislikes:
                    system_content += (
                        f" 用户明确不喜欢: {json.dumps(dislikes, ensure_ascii=False)};"
                    )
            if inferences.get("top_interests"):
                system_content += f" 核心兴趣: {json.dumps(inferences.get('top_interests', []), ensure_ascii=False)};"
            if inferences.get("summary"):
                system_content += f" 偏好概要: {inferences['summary']}"
        system_msg = {"role": "system", "content": system_content}
        messages = [system_msg] + self._history

        tool_calls_log: list[dict] = []

        yield self._sse("status", "正在分析...")

        for _round in range(self.max_tool_rounds + 1):
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
                # Emit thinking event before executing tools
                thinking = msg.content or ""
                if not thinking:
                    names = [
                        self._tool_name_zh(tc.function.name) for tc in msg.tool_calls
                    ]
                    thinking = "正在" + "、".join(names)
                yield self._sse("thinking", {"text": thinking, "round": _round + 1})

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

            level = self._collect_behavior_signals()
            if level == "full":
                await self._infer_preferences("full")
            elif level == "lite":
                await self._infer_preferences("lite")

            ctx = self.context_stats()
            yield self._sse("tool_calls", tool_calls_log)
            yield self._sse(
                "context",
                {
                    "history_tokens": ctx["history_tokens"],
                    "exchanges": ctx["exchanges"],
                },
            )
            yield self._sse("done", {"trimmed": trimmed, "session_id": sid})
            return

        # Max rounds exceeded
        reply = "抱歉，处理您的请求需要更多轮次，请简化提问。"
        self._history.append({"role": "assistant", "content": reply})
        self._save_history()
        self._collect_behavior_signals()
        yield self._sse("token", reply)
        yield self._sse("done", {"session_id": sid})
        return

    @staticmethod
    def _sse(event: str, data) -> str:
        """Format an SSE event string."""
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n"

    @staticmethod
    def _tool_name_zh(name: str) -> str:
        """Map a tool name to its Chinese description for thinking events."""
        _map = {
            "query_news": "查询新闻数据库",
            "get_stats": "获取站点运行统计",
            "search_semantic": "执行语义搜索",
            "fetch_article": "抓取文章内容并生成摘要",
            "my_preferences": "查询用户偏好分析",
            "update_preference": "更新用户偏好设置",
        }
        return _map.get(name, name)

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

    # ── time-decay helpers ─────────────────────────────────────────────

    @staticmethod
    def _now_iso() -> str:
        return __import__("datetime").datetime.now().isoformat()

    def _decay_weight(self, entry: dict, halflife_days: int | None = None) -> float:
        if halflife_days is None:
            halflife_days = self.signal_halflife_days
        """Apply exponential time decay. Returns effective weight after decay."""
        count = entry.get("count", 0) if isinstance(entry, dict) else entry
        if isinstance(entry, dict) and "last_ts" in entry:
            try:
                last = __import__("datetime").datetime.fromisoformat(entry["last_ts"])
                days = (__import__("datetime").datetime.now() - last).days
                decay = 0.5 ** (max(0, days) / halflife_days)
                return count * decay
            except (ValueError, TypeError):
                return float(count)
        return float(count)

    @staticmethod
    def _confidence_label(conf: float) -> str:
        if conf >= 0.8:
            return "高"
        if conf >= 0.5:
            return "中"
        return "低"

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

    def _bump_signal(self, signals_dict: dict, key: str):
        """Increment a time-decayed signal entry."""
        now = self._now_iso()
        entry = signals_dict.get(key, {})
        if isinstance(entry, (int, float)):
            entry = {"count": entry, "last_ts": now}
        signals_dict[key] = {
            "count": (entry.get("count", 0) if isinstance(entry, dict) else entry) + 1,
            "last_ts": now,
        }

    def _collect_behavior_signals(self):
        """Extract time-decayed heuristic signals from the latest exchange.

        Returns "none" | "lite" | "full" to indicate what inference level is due.
        """
        signals = self._preferences.setdefault("signals", {})
        signals.setdefault("queried_sites", {})
        signals.setdefault("queried_tags", {})
        signals.setdefault("used_tools", {})
        signals.setdefault("searched_topics", [])
        signals.setdefault("fetched_urls", [])
        signals.setdefault("total_exchanges", 0)

        for msg in reversed(self._history):
            if msg["role"] == "user":
                break
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    tool_name = fn["name"]
                    try:
                        tool_args = json.loads(fn["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}

                    self._bump_signal(signals["used_tools"], tool_name)

                    site = tool_args.get("site_name")
                    if site and tool_name in ("query_news", "get_stats"):
                        self._bump_signal(signals["queried_sites"], site)

                    tag = tool_args.get("tag")
                    if tag and tool_name == "query_news":
                        self._bump_signal(signals["queried_tags"], tag)

                    if tool_name == "search_semantic":
                        query = tool_args.get("query", "")
                        if query:
                            topics = signals["searched_topics"]
                            topics.append(query)
                            signals["searched_topics"] = topics[-20:]

                    if tool_name == "fetch_article":
                        url = tool_args.get("url", "")
                        if url and url not in signals["fetched_urls"]:
                            signals["fetched_urls"].append(url)
                            signals["fetched_urls"] = signals["fetched_urls"][-20:]

        signals["total_exchanges"] += 1
        self._save_preferences()

        total = signals["total_exchanges"]
        if total % self.pref_full_interval == 0:
            logger.info(
                "[ChatAgent] Triggering FULL preference inference at %d exchanges",
                total,
            )
            return "full"
        if total % self.pref_lite_interval == 0:
            logger.info(
                "[ChatAgent] Triggering LITE preference inference at %d exchanges",
                total,
            )
            return "lite"
        return "none"

    def _compute_confidence(self, interest: str) -> float:
        """Estimate confidence (0–1) for a given interest based on signal consistency."""
        signals = self._preferences.get("signals", {})
        tags = signals.get("queried_tags", {})
        entry = tags.get(interest, {})
        count = entry.get("count", 0) if isinstance(entry, dict) else entry
        if count >= 3:
            return 0.9
        if count >= 2:
            return 0.6 + min(0.15, (count - 2) * 0.05)
        if count >= 1:
            return 0.3 + min(0.15, count * 0.05)
        return 0.15

    async def _infer_preferences(self, mode: str = "full"):
        """Use LLM to analyze behavior signals and infer user preferences.

        mode: "lite" — only extract top_interests (fast, low token cost)
              "full" — full analysis with summary, sources, behavior pattern
        """
        signals = self._preferences.get("signals", {})
        existing = self._preferences.get("inferences", {})

        def _weighted_dict(raw: dict) -> dict:
            return {k: round(self._decay_weight(v), 2) for k, v in raw.items()}

        weighted_tags = _weighted_dict(signals.get("queried_tags", {}))
        weighted_sites = _weighted_dict(signals.get("queried_sites", {}))
        weighted_tools = _weighted_dict(signals.get("used_tools", {}))

        if mode == "lite":
            prompt = f"""根据用户行为信号，提取核心兴趣标签（最多5个）。
查询标签频次（已时间衰减）: {json.dumps(weighted_tags, ensure_ascii=False)}
查询站点频次（已时间衰减）: {json.dumps(weighted_sites, ensure_ascii=False)}
请输出 JSON: {{"top_interests": ["兴趣1", "兴趣2", ...]}}"""
            max_tok = 128
            system = (
                "你是用户行为分析专家。输出严格的 JSON，不要额外文字。只提取兴趣标签。"
            )
        else:
            overrides = self._preferences.get("explicit_overrides", {})
            prompt = f"""你是用户偏好分析专家。根据以下用户行为信号，推断用户的核心兴趣和偏好。

行为信号（已时间衰减）:
- 查询标签频率: {json.dumps(weighted_tags, ensure_ascii=False)}
- 查询站点频率: {json.dumps(weighted_sites, ensure_ascii=False)}
- 工具使用频率: {json.dumps(weighted_tools, ensure_ascii=False)}
- 语义搜索主题: {json.dumps(signals.get("searched_topics", []), ensure_ascii=False)}
- 抓取文章数: {len(signals.get("fetched_urls", []))}
- 总对话轮次: {signals.get("total_exchanges", 0)}
- 用户显式偏好（最高优先级）: {json.dumps(overrides, ensure_ascii=False) if overrides else "无"}

已有偏好推断: {json.dumps(existing, ensure_ascii=False) if existing else "无"}

请综合以上信号分析用户核心兴趣，输出 JSON：
{{"summary": "一二句总结用户整体偏好", "top_interests": ["兴趣1", ...], "preferred_sources": ["来源1", ...], "behavior_pattern": "用户行为模式简述"}}"""
            max_tok = 256
            system = "你是用户行为分析专家。输出严格的 JSON，不要额外文字。"

        try:
            response = await self.call_llm_async(
                system_prompt=system,
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=max_tok,
            )
            inferences = self.parse_json_response(response)
            if isinstance(inferences, list):
                inferences = inferences[0] if inferences else {}
            if isinstance(inferences, dict):
                inferences["inferred_at"] = self._now_iso()
                inferences["based_on_exchanges"] = signals.get("total_exchanges", 0)
                inferences["mode"] = mode
                if "top_interests" in inferences:
                    inferences["interest_confidence"] = {
                        interest: round(self._compute_confidence(interest), 2)
                        for interest in inferences["top_interests"]
                    }
                if mode == "lite" and existing:
                    existing.update(inferences)
                    self._preferences["inferences"] = existing
                else:
                    self._preferences["inferences"] = inferences
                self._save_preferences()
                logger.info(
                    "[ChatAgent] Updated user preference inferences (%s): %s",
                    mode,
                    inferences.get("summary", inferences.get("top_interests", "")),
                )
        except Exception as e:
            logger.warning("[ChatAgent] Preference inference failed: %s", e)

    def _format_preferences(self) -> str:
        """Format preferences for my_preferences tool output."""
        inferences = self._preferences.get("inferences", {})
        signals = self._preferences.get("signals", {})
        overrides = self._preferences.get("explicit_overrides", {})

        if not inferences and not signals.get("total_exchanges"):
            return "[偏好分析]\n暂无偏好数据。多和我对话后，我会自动分析你的兴趣偏好。"

        parts = []

        # Explicit overrides first (highest priority)
        if overrides:
            likes = [k for k, v in overrides.items() if v.get("action") == "like"]
            dislikes = [k for k, v in overrides.items() if v.get("action") == "dislike"]
            if likes:
                parts.append(f"明确喜欢: {', '.join(likes)}")
            if dislikes:
                parts.append(f"明确不喜欢: {', '.join(dislikes)}")

        if inferences.get("summary"):
            parts.append(f"偏好概要: {inferences['summary']}")

        if inferences.get("top_interests"):
            conf_map = inferences.get("interest_confidence", {})
            labeled = []
            for interest in inferences["top_interests"]:
                conf = conf_map.get(interest, 0.5)
                label = self._confidence_label(conf)
                icon = {"高": "●", "中": "◐", "低": "○"}.get(label, "○")
                labeled.append(f"{interest} [{icon}{label}]")
            parts.append(f"核心兴趣: {', '.join(labeled)}")

        if inferences.get("preferred_sources"):
            parts.append(f"偏好来源: {', '.join(inferences['preferred_sources'])}")

        if inferences.get("behavior_pattern"):
            parts.append(f"行为模式: {inferences['behavior_pattern']}")

        # Show decay-weighted tag stats
        if signals.get("queried_tags"):
            weighted = [
                (t, round(self._decay_weight(v), 1))
                for t, v in signals["queried_tags"].items()
            ]
            weighted.sort(key=lambda x: x[1], reverse=True)
            top5 = weighted[:5]
            parts.append(f"近期活跃标签: {', '.join(f'{t}({w:.1f})' for t, w in top5)}")

        parts.append(
            f"统计: 共 {signals.get('total_exchanges', 0)} 轮对话, "
            f"使用 {len(signals.get('queried_sites', {}))} 个站点"
        )

        if inferences.get("mode") == "lite":
            parts.append("[注意] 偏好画像处于初始化阶段，经过更多对话后会更加精确。")

        return "[偏好分析]\n" + "\n".join(parts)

    # ── daily report generation ──────────────────────────────────────

    async def generate_daily_report(self, sites: list[str] | None = None) -> dict:
        """Query recent news and generate an LLM summary report.

        Returns a dict with ``report`` (str) and ``stats`` (dict) suitable
        for pushing through the notification dispatcher.
        """
        now = self._now_iso()
        store = self.news_store
        if not store:
            return {"report": "", "error": "No data store available"}

        all_items = []
        target_sites = sites or []
        for site in target_sites:
            items = store.query_items(site_name=site, limit=20)
            all_items.extend(items)

        if not all_items:
            return {
                "report": f"## 每日新闻简报 ({now[:10]})\n\n暂无新数据。",
                "stats": {"total_items": 0, "sites": []},
                "generated_at": now,
            }

        # Build summary of items by site
        from collections import Counter

        site_counts = Counter(it["site_name"] for it in all_items)
        tag_counts = Counter(it.get("tag", "其他") for it in all_items)

        # Prepare a prompt-friendly item list
        item_lines = []
        for it in all_items[:30]:
            item_lines.append(
                f"- [{it.get('tag', '')}] {it['title'][:80]} "
                f"({it.get('site_name', '?')})"
            )
        items_text = "\n".join(item_lines)

        prompt = (
            f"今天是 {now[:10]}。以下是过去一段时间监控到的新闻/文章摘要：\n\n"
            f"站点覆盖: {', '.join(site_counts.keys())}\n"
            f"标签分布: {dict(tag_counts.most_common(8))}\n\n"
            f"最近条目:\n{items_text}\n\n"
            f"请用 3-5 句中文字生成每日简报摘要，"
            f"突出最重要的变化和新出现的话题，语气简洁专业。"
        )

        summary = ""
        try:
            response = await self.async_client.chat.completions.create(
                model=self.llm_config.get("model", "glm-4-flash"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=512,
            )
            summary = response.choices[0].message.content or ""
        except Exception as e:
            logger.warning("[ChatAgent] Daily report LLM call failed: %s", e)
            summary = "（LLM 摘要生成失败，请检查 API 连接）"

        report = (
            f"## 每日新闻简报 ({now[:10]})\n\n"
            f"{summary}\n\n"
            f"**数据概览**: {sum(site_counts.values())} 条新内容，"
            f"覆盖 {len(site_counts)} 个站点\n"
            f"**热门标签**: {', '.join(f'{k}({v})' for k, v in tag_counts.most_common(5))}"
        )

        return {
            "report": report,
            "stats": {
                "total_items": sum(site_counts.values()),
                "sites": [{"name": k, "count": v} for k, v in site_counts.items()],
                "tags": dict(tag_counts.most_common(10)),
            },
            "generated_at": now,
        }

    def clear_history(self, session_id: str | None = None):
        self._activate_session(session_id)
        self._history.clear()
        self._total_trimmed = 0
        self._total_compressed = 0
        self._total_cleaned = 0
        self._save_history()
        logger.info(
            "[ChatAgent] History cleared for session %s", (session_id or "default")[:8]
        )

    def list_sessions(self) -> list[dict]:
        """Return active session metadata."""
        result = []
        for sid, data in self._sessions.items():
            msg_count = len(data.get("history", []))
            exchanges = sum(
                1 for m in data.get("history", []) if m.get("role") == "user"
            )
            result.append(
                {
                    "session_id": sid,
                    "messages": msg_count,
                    "exchanges": exchanges,
                    "created_at": data.get("created_at", ""),
                }
            )
        result.sort(key=lambda s: s["created_at"], reverse=True)
        return result
