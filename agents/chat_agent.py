"""ChatAgent: conversational assistant with tool-calling for the monitoring dashboard.

Uses LangChain for tool definitions (@tool decorator), model management
(ChatOpenAI/ChatAnthropic), and streaming.  Context management (compress ->
clean -> trim) is handled by ContextManager; session management, input
validation, and preference inference remain custom.
"""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path

import httpx

from .base_agent import BaseAgent
from .context_manager import (
    ContextManager,
    MAX_HISTORY_TOKENS,
    MIN_EXCHANGES,
    COMPRESSION_THRESHOLD,
    COMPRESSION_TARGET,
    MAX_TOOL_RESULTS,
)
from .tools import build_all_tools

logger = logging.getLogger(__name__)

# ── HTML cleaning (shared with fetcher) ────────────────────────────────
SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
WHITESPACE_RE = re.compile(r"\s+")

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

# Tools are now built dynamically via build_all_tools()
# (see agents/tools/__init__.py with 18 LangChain @tool functions)

CHAT_HISTORY_FILE = Path("data/chat_history.json")
PREFERENCES_FILE = Path("data/user_preferences.json")
PREFERENCE_LITE_INTERVAL = 2
PREFERENCE_FULL_INTERVAL = 5
SIGNAL_HALFLIFE_DAYS = 14
MAX_TOOL_ROUNDS = 3


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
        alert_store=None,
        story_watch=None,
        hybrid_searcher=None,
        coordinator=None,
        evolution=None,
        max_history_tokens: int | None = None,
    ):
        super().__init__("Chat", config)
        self.news_store = news_store
        self.paper_store = paper_store
        self.vector_store = vector_store
        self.alert_store = alert_store
        self.story_watch = story_watch
        self.hybrid_searcher = hybrid_searcher
        self._coordinator = coordinator
        self._evolution = evolution

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

        # LangChain tools (built dynamically with dependency injection)
        self._tools = build_all_tools(self)

        # Context manager (extracted to agents/context_manager.py)
        self._ctx = ContextManager(
            max_history_tokens=self.max_history_tokens,
            min_exchanges=self.min_exchanges,
            compression_threshold=self.compression_threshold,
            compression_target=self.compression_target,
            max_tool_results=self.max_tool_results,
        )

        self._preferences: dict = {}
        self.pref_lite_interval = chat_cfg.get(
            "pref_lite_interval", PREFERENCE_LITE_INTERVAL
        )
        self.pref_full_interval = chat_cfg.get(
            "preference_full_interval", PREFERENCE_FULL_INTERVAL
        )
        self.signal_halflife_days = chat_cfg.get(
            "signal_halflife_days", SIGNAL_HALFLIFE_DAYS
        )
        self._fetch_client = None

        # Session support
        self._sessions: dict[str, dict] = {}
        self._current_session_id: str | None = None
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

    # context management (delegated to ContextManager)

    async def _maybe_compress(self):
        await self._ctx.maybe_compress(self._history, self.model)

    def _cleanup_old_tool_results(self):
        self._ctx.cleanup_old_tool_results(self._history)

    def _trim_context(self) -> int:
        self._ctx.max_history_tokens = self.max_history_tokens
        self._ctx.min_exchanges = self.min_exchanges
        result = self._ctx.trim_context(self._history)
        self._total_trimmed = self._ctx.total_trimmed
        return result

    def context_stats(self) -> dict:
        stats = self._ctx.stats(self._history)
        stats["lifetime_trimmed"] = self._total_trimmed
        stats["lifetime_compressed"] = (
            self._ctx.total_compressed or self._total_compressed
        )
        stats["lifetime_cleaned"] = self._ctx.total_cleaned or self._total_cleaned
        return stats

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
        self._save_history()

        system_msg = {"role": "system", "content": self._build_system_prompt()}
        messages = [system_msg] + list(self._history)

        tool_calls_log: list[dict] = []
        model = self.model.bind_tools(self._tools)

        for _round in range(self.max_tool_rounds + 1):
            result = await model.ainvoke(messages)

            if result.tool_calls:
                parsed = []
                for tc in result.tool_calls:
                    name = tc.get("name", "")
                    args = tc.get("args", {})
                    if not args:
                        raw = tc.get("function", {}).get("arguments", "{}")
                        try:
                            args = (
                                json.loads(raw) if isinstance(raw, str) else (raw or {})
                            )
                        except Exception:
                            args = {}
                    parsed.append((tc, name, args))

                async def _exec_one(name, args):
                    for t in self._tools:
                        if t.name == name:
                            try:
                                r = await t.ainvoke(args)
                                return str(r) if r else ""
                            except Exception as e:
                                return f"[{name} error] {e}"
                    return f"[unknown tool] {name}"

                tasks = [_exec_one(name, args) for _, name, args in parsed]
                tool_results = await asyncio.gather(*tasks)

                assistant_msg = {
                    "role": "assistant",
                    "content": result.content or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args, ensure_ascii=False),
                            },
                        }
                        for tc, name, args in parsed
                    ],
                }
                messages.append(assistant_msg)
                self._history.append(assistant_msg)

                for i, (tc, name, args) in enumerate(parsed):
                    tr = tool_results[i]
                    tool_calls_log.append(
                        {
                            "tool": name,
                            "args": args,
                            "result": tr[:2000],
                        }
                    )
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tr,
                    }
                    messages.append(tool_msg)
                    self._history.append(tool_msg)
                continue

            reply = result.content or ""
            self._history.append({"role": "assistant", "content": reply})

            await self._maybe_compress()
            self._cleanup_old_tool_results()
            trimmed = self._trim_context()
            self._save_history()

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

        reply = "抱歉，处理您的请求需要更多轮次，请简化提问。"
        self._history.append({"role": "assistant", "content": reply})
        self._save_history()
        self._collect_behavior_signals()
        return {
            "reply": reply,
            "tool_calls": tool_calls_log,
            "context": self.context_stats(),
            "context_trimmed": 0,
            "session_id": sid,
        }

    # streaming chat (SSE)

    async def chat_stream(self, user_message: str, session_id: str | None = None):
        sid = self._activate_session(session_id)
        rejection = self._validate_input(user_message)
        if rejection:
            self._history.append({"role": "assistant", "content": rejection})
            self._save_history()
            yield self._sse("token", rejection)
            yield self._sse("done", {"rejected": True, "session_id": sid})
            return

        self._history.append({"role": "user", "content": user_message})
        self._save_history()

        system_msg = {"role": "system", "content": self._build_system_prompt()}
        messages = [system_msg] + list(self._history)

        tool_calls_log: list[dict] = []
        yield self._sse("status", "正在分析...")

        model = self.model.bind_tools(self._tools)

        for _round in range(self.max_tool_rounds + 1):
            result = await model.ainvoke(messages)

            if result.tool_calls:
                parsed = []
                for tc in result.tool_calls:
                    name = tc.get("name", "")
                    args = tc.get("args", {})
                    if not args:
                        raw = tc.get("function", {}).get("arguments", "{}")
                        try:
                            args = (
                                json.loads(raw) if isinstance(raw, str) else (raw or {})
                            )
                        except Exception:
                            args = {}
                    parsed.append((tc, name, args))

                thinking_text = result.content or ""
                if not thinking_text:
                    names = ", ".join(name for _, name, _ in parsed)
                    thinking_text = f"正在调用: {names}"
                yield self._sse(
                    "thinking", {"text": thinking_text, "round": _round + 1}
                )

                for tc, name, args in parsed:
                    yield self._sse("tool_call", {"tool": name, "args": args})

                async def _exec_one(name, args):
                    for t in self._tools:
                        if t.name == name:
                            try:
                                r = await t.ainvoke(args)
                                return str(r) if r else ""
                            except Exception as e:
                                return f"[{name} error] {e}"
                    return f"[unknown tool] {name}"

                tasks = [_exec_one(name, args) for _, name, args in parsed]
                tool_results = await asyncio.gather(*tasks)

                for i, (tc, name, args) in enumerate(parsed):
                    tr = tool_results[i]
                    yield self._sse("tool_result", {"tool": name, "result": tr[:2000]})

                assistant_msg = {
                    "role": "assistant",
                    "content": result.content or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args, ensure_ascii=False),
                            },
                        }
                        for tc, name, args in parsed
                    ],
                }
                messages.append(assistant_msg)
                self._history.append(assistant_msg)

                for i, (tc, name, args) in enumerate(parsed):
                    tr = tool_results[i]
                    tool_calls_log.append(
                        {
                            "tool": name,
                            "args": args,
                            "result": tr[:2000],
                        }
                    )
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tr,
                    }
                    messages.append(tool_msg)
                    self._history.append(tool_msg)
                continue

            yield self._sse("status", "正在生成回复...")

            reply_parts = []
            async for chunk in self.model.astream(messages):
                if chunk.content:
                    reply_parts.append(chunk.content)
                    yield self._sse("token", chunk.content)

            reply = "".join(reply_parts)
            self._history.append({"role": "assistant", "content": reply})

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

        reply = "抱歉，处理您的请求需要更多轮次，请简化提问。"
        self._history.append({"role": "assistant", "content": reply})
        self._save_history()
        self._collect_behavior_signals()
        yield self._sse("token", reply)
        yield self._sse("done", {"session_id": sid})

    @staticmethod
    def _sse(event: str, data) -> str:
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n"

    def _build_system_prompt(self) -> str:
        prompt_path = Path("prompts/chat_system.txt")
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
        else:
            content = "你是 News Agent Monitor 的智能对话助手。"

        inferences = self._preferences.get("inferences", {})
        overrides = self._preferences.get("explicit_overrides", {})
        if inferences.get("summary") or overrides:
            content += "\n\n用户偏好参考（根据历史行为推断，仅供参考，不要刻意迎合）:"
            if overrides:
                likes = [k for k, v in overrides.items() if v.get("action") == "like"]
                dislikes = [
                    k for k, v in overrides.items() if v.get("action") == "dislike"
                ]
                if likes:
                    content += (
                        f" 用户明确喜欢: {json.dumps(likes, ensure_ascii=False)};"
                    )
                if dislikes:
                    content += (
                        f" 用户明确不喜欢: {json.dumps(dislikes, ensure_ascii=False)};"
                    )
            if inferences.get("top_interests"):
                content += f" 核心兴趣: {json.dumps(inferences.get('top_interests', []), ensure_ascii=False)};"
            if inferences.get("summary"):
                content += f" 偏好概要: {inferences['summary']}"
        return content

    def _load_history(self):
        """Load all sessions from JSON file. Migrates legacy single-session format."""
        try:
            if CHAT_HISTORY_FILE.exists():
                data = json.loads(CHAT_HISTORY_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    # Legacy format: single list → migrate to sessions dict
                    sid = str(uuid.uuid4())
                    self._sessions[sid] = self._new_session_data()
                    self._sessions[sid]["history"] = data
                    self._default_session = self._sessions[sid]
                    logger.info(
                        "[ChatAgent] Migrated legacy history (%d msgs) → session %s",
                        len(data),
                        sid[:8],
                    )
                elif isinstance(data, dict):
                    self._sessions = data
                    # Restore default session from first loaded session
                    if self._sessions:
                        first = next(iter(self._sessions.values()))
                        self._default_session = first
                    logger.info(
                        "[ChatAgent] Loaded %d sessions from %s",
                        len(self._sessions),
                        CHAT_HISTORY_FILE,
                    )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[ChatAgent] Failed to load chat history: %s", e)

    def _save_history(self):
        """Persist all sessions to JSON file."""
        try:
            CHAT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            CHAT_HISTORY_FILE.write_text(
                json.dumps(self._sessions, ensure_ascii=False, indent=2),
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

        Collects:
        - Explicit: tool calls, sites, tags, search topics
        - Implicit satisfaction: fetch_article after query = deep interest;
          same tag queried 3+ times = strong signal; empty results = weak signal

        Returns "none" | "lite" | "full" to indicate what inference level is due.
        """
        signals = self._preferences.setdefault("signals", {})
        signals.setdefault("queried_sites", {})
        signals.setdefault("queried_tags", {})
        signals.setdefault("used_tools", {})
        signals.setdefault("searched_topics", [])
        signals.setdefault("fetched_urls", [])
        signals.setdefault("interest_depth", {})
        signals.setdefault("total_exchanges", 0)
        satisfaction = signals.setdefault("satisfaction", {})
        satisfaction.setdefault("articles_read", 0)
        satisfaction.setdefault("empty_queries", 0)
        satisfaction.setdefault("keyword_retries", 0)

        # Track query tags and fetch_article across this exchange
        exchange_query_tags: list[str] = []
        exchange_fetched: bool = False
        exchange_had_empty: bool = False

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
                    if site and tool_name in (
                        "search",
                        "get_snapshot",
                        "get_run_log",
                        "get_circuit_status",
                        "get_evolution_log",
                    ):
                        self._bump_signal(signals["queried_sites"], site)

                    tag = tool_args.get("tag")
                    if tag and tool_name in ("search",):
                        self._bump_signal(signals["queried_tags"], tag)
                        exchange_query_tags.append(tag)

                    if tool_name in ("search",):
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
                        exchange_fetched = True

            # Detect empty tool results
            if msg.get("role") == "tool" and msg.get("content", "").startswith(
                "[查询结果] 未找到"
            ):
                exchange_had_empty = True

        # ── Satisfaction signals ─────────────────────────────────────
        if exchange_fetched:
            satisfaction["articles_read"] += 1
            # Bump interest_depth for tags from the same exchange
            for tag in exchange_query_tags:
                depth = signals["interest_depth"].setdefault(tag, 0)
                signals["interest_depth"][tag] = depth + 1

        if exchange_had_empty:
            satisfaction["empty_queries"] += 1
            # If user retried with different keywords after empty result
            if exchange_query_tags:
                satisfaction["keyword_retries"] += 1

        # Boost confidence for deep-interest tags (queried 3+ times)
        for tag, depth in signals["interest_depth"].items():
            if depth >= 3 and tag not in signals.get("queried_tags", {}):
                signals["queried_tags"][tag] = {
                    "count": depth,
                    "last_ts": self._now_iso(),
                }

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
        """Estimate confidence (0–1) combining explicit signals, depth, and consistency."""
        signals = self._preferences.get("signals", {})
        overrides = self._preferences.get("explicit_overrides", {})

        # Explicit overrides get max confidence
        if interest in overrides:
            return overrides[interest].get("confidence", 0.9)

        # Base: query tag frequency
        tags = signals.get("queried_tags", {})
        entry = tags.get(interest, {})
        count = entry.get("count", 0) if isinstance(entry, dict) else entry

        # Boost: interest_depth (user read articles from this tag)
        depth = signals.get("interest_depth", {}).get(interest, 0)
        effective = count + depth * 1.5  # reading is a stronger signal than querying

        if effective >= 5:
            return 0.95
        if effective >= 3:
            return min(0.9, 0.7 + effective * 0.05)
        if effective >= 2:
            return 0.5 + min(0.2, effective * 0.05)
        if effective >= 1:
            return 0.3 + min(0.15, effective * 0.05)
        return 0.15

    async def _infer_preferences(self, mode: str = "full"):
        """Infer user preferences from behavior signals.

        mode: "lite" — pure statistical (zero LLM cost), compute top_interests
              "full" — statistical top_interests + LLM for summary text

        Design: structured data (top_interests, preferred_sources, confidence)
        is computed by statistical rules. LLM is only used in full mode to
        generate human-readable summary and behavior_pattern text.
        """
        signals = self._preferences.get("signals", {})
        existing = self._preferences.get("inferences", {})

        def _weighted_dict(raw: dict) -> dict:
            return {k: round(self._decay_weight(v), 2) for k, v in raw.items()}

        weighted_tags = _weighted_dict(signals.get("queried_tags", {}))
        weighted_sites = _weighted_dict(signals.get("queried_sites", {}))

        # ── Statistical computation (shared by lite and full) ──────────
        # Sort by decayed weight, include explicit likes at top
        overrides = self._preferences.get("explicit_overrides", {})
        explicit_likes = {k for k, v in overrides.items() if v.get("action") == "like"}

        sorted_tags = sorted(weighted_tags.items(), key=lambda x: x[1], reverse=True)
        top_interests = [t for t, w in sorted_tags if w > 0.1]
        # Explicit likes always appear first
        for tag in explicit_likes:
            if tag not in top_interests:
                top_interests.insert(0, tag)
        top_interests = top_interests[:5]

        sorted_sites = sorted(weighted_sites.items(), key=lambda x: x[1], reverse=True)
        preferred_sources = [s for s, w in sorted_sites[:3] if w > 0.1]

        # Compute confidence for each interest
        interest_confidence = {
            interest: round(self._compute_confidence(interest), 2)
            for interest in top_interests
        }

        # ── Build inferences dict ──────────────────────────────────────
        inferences = {
            "inferred_at": self._now_iso(),
            "based_on_exchanges": signals.get("total_exchanges", 0),
            "mode": mode,
            "top_interests": top_interests,
            "interest_confidence": interest_confidence,
            "preferred_sources": preferred_sources,
        }

        if mode == "lite":
            # Lite: pure statistical, zero LLM cost
            if existing:
                existing.update(inferences)
                self._preferences["inferences"] = existing
            else:
                self._preferences["inferences"] = inferences
            self._save_preferences()
            logger.info(
                "[ChatAgent] Updated lite preferences (statistical): %s",
                top_interests,
            )
            return

        # ── Full mode: LLM only for text description ──────────────────
        depth_tags = {k: v for k, v in signals.get("interest_depth", {}).items()}
        satisfaction = signals.get("satisfaction", {})

        prompt = f"""根据已计算出的结构化偏好，生成一段简洁的用户画像描述。

统计结果:
- 核心兴趣（按衰减权重排序）: {json.dumps(top_interests, ensure_ascii=False)}
- 置信度: {json.dumps(interest_confidence, ensure_ascii=False)}
- 偏好来源: {json.dumps(preferred_sources, ensure_ascii=False)}
- 显式喜欢: {list(explicit_likes) if explicit_likes else "无"}
- 搜索主题: {json.dumps(signals.get("searched_topics", [])[-5:], ensure_ascii=False)}
- 深度关注标签（重复查询≥3次）: {json.dumps(depth_tags, ensure_ascii=False)}
- 阅读文章数: {satisfaction.get("articles_read", 0)}
- 总对话轮次: {signals.get("total_exchanges", 0)}

请输出 JSON：
{{"summary": "用一两句话总结用户整体偏好", "behavior_pattern": "简述用户行为模式（如活跃时间、查询风格、偏好稳定性）"}}"""

        try:
            response = await self.call_llm_async(
                system_prompt="你是用户行为分析专家。输出严格的 JSON，不要额外文字。",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=200,
            )
            text_inferences = self.parse_json_response(response)
            if isinstance(text_inferences, list):
                text_inferences = text_inferences[0] if text_inferences else {}
            if isinstance(text_inferences, dict):
                inferences["summary"] = text_inferences.get("summary", "")
                inferences["behavior_pattern"] = text_inferences.get(
                    "behavior_pattern", ""
                )
        except Exception as e:
            logger.warning("[ChatAgent] Preference LLM summary failed: %s", e)
            inferences["summary"] = (
                f"用户主要关注 {', '.join(top_interests[:3])} 相关内容"
            )
            inferences["behavior_pattern"] = "偏好分析中"

        self._preferences["inferences"] = inferences
        self._save_preferences()
        logger.info(
            "[ChatAgent] Updated full preferences: %s",
            inferences.get("summary", ""),
        )

    def _format_preferences(self) -> str:
        """Format preferences for preferences tool output."""
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
            result = await self.model.ainvoke([{"role": "user", "content": prompt}])
            summary = result.content or ""
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
