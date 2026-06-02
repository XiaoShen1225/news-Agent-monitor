"""Context management: sliding window + exchange-boundary trimming.

Three-stage strategy:
  1. Compress: LLM-summarize oldest exchanges when token usage > threshold
  2. Clean: Truncate old tool result contents, keeping most recent N intact
  3. Trim: Remove oldest complete exchanges until token budget is met
"""

import logging
import re

logger = logging.getLogger(__name__)

# ── Token estimation helpers ───────────────────────────────────────────
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_ENGLISH_RE = re.compile(r"[a-zA-Z]+")

MAX_HISTORY_TOKENS = 12000
MIN_EXCHANGES = 1
COMPRESSION_THRESHOLD = 0.6
COMPRESSION_TARGET = 0.4
MAX_TOOL_RESULTS = 5


def count_tokens(text: str) -> int:
    """Estimate token count for Chinese + English mixed text.

    Heuristic calibrated against typical multilingual tokenizers:
    - Chinese character ≈ 1.2 tokens
    - English word ≈ 1.3 tokens
    - Other characters ≈ 0.3 tokens
    """
    chinese = len(_CHINESE_RE.findall(text))
    english = len(_ENGLISH_RE.findall(text))
    other = len(text) - chinese - english
    return int(chinese * 1.2 + english * 1.3 + other * 0.3)


def messages_tokens(messages: list[dict]) -> int:
    """Total estimated tokens across a message list."""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, str):
            total += count_tokens(content)
        if m.get("tool_calls"):
            for tc in m["tool_calls"]:
                args = tc.get("function", {}).get("arguments", "")
                total += count_tokens(args) + 10
    return total


def get_exchanges(history: list[dict]) -> list[list[dict]]:
    """Partition history into exchange groups.

    Each exchange starts with a ``user`` message and includes all
    subsequent assistant + tool messages until the next user message.
    """
    exchanges: list[list[dict]] = []
    current: list[dict] = []
    for msg in history:
        if msg["role"] == "user" and current:
            exchanges.append(current)
            current = []
        current.append(msg)
    if current:
        exchanges.append(current)
    return exchanges


class ContextManager:
    """Manages conversation history token budget via compress / clean / trim."""

    def __init__(
        self,
        max_history_tokens: int = MAX_HISTORY_TOKENS,
        min_exchanges: int = MIN_EXCHANGES,
        compression_threshold: float = COMPRESSION_THRESHOLD,
        compression_target: float = COMPRESSION_TARGET,
        max_tool_results: int = MAX_TOOL_RESULTS,
    ):
        self.max_history_tokens = max_history_tokens
        self.min_exchanges = min_exchanges
        self.compression_threshold = compression_threshold
        self.compression_target = compression_target
        self.max_tool_results = max_tool_results
        self.total_compressed = 0
        self.total_cleaned = 0
        self.total_trimmed = 0

    # ── compression ──────────────────────────────────────────────────

    async def compress_exchanges(self, exchanges: list[list[dict]], llm) -> str:
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
            result = await llm.ainvoke([{"role": "user", "content": prompt}])
            return result.content or ""
        except Exception as e:
            logger.warning("[ContextManager] Compression summary failed: %s", e)
            return ""

    async def maybe_compress(self, history: list[dict], llm):
        """Proactively compress oldest exchanges when token usage exceeds threshold."""
        tokens = messages_tokens(history)
        if tokens <= self.max_history_tokens * self.compression_threshold:
            return history

        exchanges = get_exchanges(history)
        if len(exchanges) <= self.min_exchanges + 1:
            return history

        compress_count = max(1, int(len(exchanges) * self.compression_target))
        compress_count = min(compress_count, len(exchanges) - self.min_exchanges)
        if compress_count <= 0:
            return history

        to_compress = exchanges[:compress_count]
        keep = exchanges[compress_count:]

        summary = await self.compress_exchanges(to_compress, llm)
        if not summary:
            return history

        history[:] = [{"role": "system", "content": f"[对话摘要] {summary}"}] + [
            m for ex in keep for m in ex
        ]
        self.total_compressed += 1
        logger.info(
            "[ContextManager] Compressed %d exchange(s) into summary (%d chars); "
            "history: ~%d tokens, %d exchanges remaining",
            compress_count,
            len(summary),
            messages_tokens(history),
            len(keep),
        )
        return history

    # ── clean ────────────────────────────────────────────────────────

    def cleanup_old_tool_results(self, history: list[dict]):
        """Truncate old tool result contents, keeping the most recent N intact."""
        tool_indices = [i for i, m in enumerate(history) if m.get("role") == "tool"]
        if len(tool_indices) <= self.max_tool_results:
            return

        cleaned = 0
        for idx in tool_indices[: -self.max_tool_results]:
            msg = history[idx]
            if len(msg.get("content", "")) > 30:
                tc_id = msg.get("tool_call_id", "unknown")
                msg["content"] = f"[已清除: 旧查询结果 — {tc_id}]"
                cleaned += 1

        if cleaned:
            self.total_cleaned += cleaned
            logger.info(
                "[ContextManager] Cleaned %d old tool result(s); %d lifetime cleaned",
                cleaned,
                self.total_cleaned,
            )

    # ── trim ─────────────────────────────────────────────────────────

    def trim_context(self, history: list[dict]) -> int:
        """Remove oldest exchanges until history fits in the token budget.

        Returns the number of exchanges trimmed.
        """
        tokens = messages_tokens(history)
        if tokens <= self.max_history_tokens:
            return 0

        exchanges = get_exchanges(history)
        if len(exchanges) <= self.min_exchanges:
            return 0

        trimmed = 0
        while len(exchanges) > self.min_exchanges:
            total = sum(messages_tokens(ex) for ex in exchanges)
            if total <= self.max_history_tokens:
                break
            exchanges.pop(0)
            trimmed += 1

        if trimmed:
            history[:] = [m for ex in exchanges for m in ex]
            self.total_trimmed += trimmed
            logger.info(
                "[ContextManager] Trimmed %d old exchange(s); history: ~%d tokens, %d exchanges, %d lifetime trimmed",
                trimmed,
                messages_tokens(history),
                len(exchanges),
                self.total_trimmed,
            )
        return trimmed

    # ── stats ────────────────────────────────────────────────────────

    def stats(self, history: list[dict]) -> dict:
        """Return current context usage for observability."""
        exchanges = 0
        for msg in history:
            if msg["role"] == "user":
                exchanges += 1
        return {
            "history_tokens": messages_tokens(history),
            "exchanges": exchanges,
            "max_history_tokens": self.max_history_tokens,
            "lifetime_trimmed": self.total_trimmed,
            "lifetime_compressed": self.total_compressed,
            "lifetime_cleaned": self.total_cleaned,
        }
