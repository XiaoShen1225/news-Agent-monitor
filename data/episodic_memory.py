"""Episodic memory: cross-session conversation summaries with keyword retrieval.

Each "episode" is a compressed summary of a conversation session, stored as
a lightweight JSON record. On new queries, relevant past episodes are retrieved
via keyword overlap and injected into the system prompt as contextual memory.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

logger = logging.getLogger(__name__)

MEMORY_FILE = Path("data/episodic_memory.json")
MAX_EPISODES = 200
EPISODE_MAX_CHARS = 800


class EpisodicMemory:
    """Persistent store of compressed session summaries.

    Thread-safe for reads; writes should be serialized per session.
    """

    def __init__(self, path: Path | None = None):
        self._path = path or MEMORY_FILE
        self._episodes: list[dict] = []
        self._load()

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._episodes = data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[EpisodicMemory] Load failed: %s", e)
            self._episodes = []

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._episodes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("[EpisodicMemory] Save failed: %s", e)

    def add(
        self,
        session_id: str,
        summary: str,
        topics: list[str],
        entities: list[str],
        exchange_count: int,
    ):
        """Add a new episodic memory for a session.

        If a session already has an episode, it is replaced (upsert).
        Old episodes beyond MAX_EPISODES are trimmed.
        """
        if not summary.strip():
            return

        summary = summary[:EPISODE_MAX_CHARS]
        now = datetime.now(timezone.utc).isoformat()

        episode = {
            "id": str(uuid.uuid4())[:8],
            "session_id": session_id,
            "summary": summary,
            "topics": topics[:10],
            "entities": entities[:10],
            "exchange_count": exchange_count,
            "created_at": now,
            "last_recalled_at": None,
            "recall_count": 0,
        }

        # Upsert: replace existing episode for same session
        existing = None
        for i, ep in enumerate(self._episodes):
            if ep.get("session_id") == session_id:
                existing = i
                break
        if existing is not None:
            episode["id"] = self._episodes[existing].get("id", episode["id"])
            self._episodes[existing] = episode
        else:
            self._episodes.append(episode)

        # Trim old episodes
        if len(self._episodes) > MAX_EPISODES:
            self._episodes = self._episodes[-MAX_EPISODES:]

        self._save()
        logger.info(
            "[EpisodicMemory] Saved episode %s (session %s, %d exchanges)",
            episode["id"],
            session_id[:8],
            exchange_count,
        )

    def retrieve(
        self, query: str = "", topics: list[str] | None = None, top_k: int = 5
    ) -> list[dict]:
        """Retrieve relevant past episodes by keyword overlap with query + topics.

        Scoring: weighted sum of topic overlap, entity match, and recency.
        """
        if not self._episodes:
            return []

        query_terms = set()
        if query:
            # Simple character bigram tokenization for Chinese
            q = query.lower().strip()
            query_terms = {q[i : i + 2] for i in range(max(len(q) - 1, 1))}
        if topics:
            query_terms.update(t.lower() for t in topics)

        if not query_terms:
            # No query context — return most recent
            recent = list(reversed(self._episodes[-top_k:]))
            for ep in recent:
                self._touch(ep)
            return recent

        scored = []
        for ep in self._episodes:
            ep_text = (
                ep.get("summary", "") + " " + " ".join(ep.get("topics", []))
            ).lower()
            ep_bigrams = {ep_text[i : i + 2] for i in range(max(len(ep_text) - 1, 1))}

            # Jaccard overlap
            overlap = len(query_terms & ep_bigrams)
            if overlap == 0:
                continue
            jaccard = overlap / len(query_terms | ep_bigrams)

            # Recency boost: newer episodes get small bonus
            try:
                created = datetime.fromisoformat(ep["created_at"])
                days_ago = (datetime.now(timezone.utc) - created).days
                recency = max(0.1, 1.0 - days_ago / 30.0)
            except (ValueError, TypeError):
                recency = 0.5

            score = jaccard * 0.7 + recency * 0.3
            scored.append((score, ep))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [ep for _, ep in scored[:top_k]]
        for ep in result:
            self._touch(ep)
        return result

    def get_recent(self, n: int = 5) -> list[dict]:
        """Return the N most recent episodes."""
        return list(reversed(self._episodes[-n:]))

    def _touch(self, episode: dict):
        """Bump recall metadata."""
        episode["recall_count"] = episode.get("recall_count", 0) + 1
        episode["last_recalled_at"] = datetime.now(timezone.utc).isoformat()

    def _extract_topics_from_messages(self, messages: list[dict]) -> list[str]:
        """Extract topic keywords from a conversation's tool calls and queries."""
        topics = Counter()
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                # Extract key terms from user queries (simple approach)
                for word in content.split():
                    word = word.strip().rstrip("?？。，,!！")
                    if len(word) >= 2:
                        topics[word] += 1
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    if name == "search":
                        if args.get("query"):
                            topics[args["query"]] += 2
                    if args.get("tag"):
                        topics[args["tag"]] += 1
        return [t for t, _ in topics.most_common(10)]
