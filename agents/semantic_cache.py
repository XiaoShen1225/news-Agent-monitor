"""Semantic cache for LLM calls — avoids redundant API round-trips.

Cache key = SHA256(normalized_prompt + model_name).
On cache hit, verifies with cosine similarity (threshold 0.92) before returning.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_FILE = Path("data/semantic_cache.json")
DEFAULT_SIMILARITY_THRESHOLD = 0.92
DEFAULT_TTL_HOURS = 24  # entries older than this are expired
MAX_ENTRIES = 500


def _normalize(text: str) -> str:
    """Normalize prompt text for hashing — strip whitespace, lower."""
    return " ".join(text.split()).lower()[:2000]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SemanticCache:
    """Lazy-loads sentence-transformers embedder; persists to JSON file."""

    def __init__(
        self,
        cache_file: str | Path = CACHE_FILE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ):
        self._file = Path(cache_file)
        self._threshold = similarity_threshold
        self._ttl = ttl_hours * 3600
        self._embedder = None
        self._store: dict[str, dict] = {}
        self._load()

    # ── public API ────────────────────────────────────────────────────

    def get(self, prompt: str, model: str = "") -> str | None:
        """Return cached response if found, else None."""
        key = self._make_key(prompt, model)
        entry = self._store.get(key)
        if not entry:
            return None
        if time.time() - entry.get("ts", 0) > self._ttl:
            del self._store[key]
            return None
        # Verify semantic similarity (guard against hash collision)
        cached_prompt = entry.get("prompt", "")
        if cached_prompt:
            emb = self._embed(prompt)
            cached_emb = entry.get("embedding")
            if cached_emb and _cosine(emb, cached_emb) < self._threshold:
                logger.debug("[SemanticCache] Low similarity — cache miss")
                return None
        logger.info("[SemanticCache] HIT — saved an LLM call")
        return entry.get("response", None)

    def set(self, prompt: str, response: str, model: str = ""):
        """Store a prompt → response pair."""
        key = self._make_key(prompt, model)
        emb = self._embed(prompt)
        self._store[key] = {
            "prompt": prompt,
            "response": response,
            "model": model,
            "embedding": emb,
            "ts": time.time(),
        }
        self._evict_if_needed()
        self._save()

    def stats(self) -> dict:
        return {
            "entries": len(self._store),
            "file": str(self._file),
            "threshold": self._threshold,
            "ttl_hours": self._ttl // 3600,
        }

    # ── internals ─────────────────────────────────────────────────────

    def _make_key(self, prompt: str, model: str) -> str:
        raw = _normalize(prompt) + "|" + (model or "")
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _embed(self, text: str) -> list[float]:
        if self._embedder is None:
            self._embedder = self._load_embedder()
        try:
            return self._embedder.encode(_normalize(text)).tolist()
        except Exception:
            return []

    def _load_embedder(self):
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(
                "infgrad/stella-base-zh-v3-1792d", local_files_only=True
            )
            # Warmup with a dummy pass
            model.encode("warmup")
            return model
        except Exception:
            logger.warning("[SemanticCache] Embedder load failed — cache disabled")
            return None

    def _load(self):
        if self._file.exists():
            try:
                self._store = json.loads(self._file.read_text(encoding="utf-8"))
                # Purge expired entries on load
                now = time.time()
                self._store = {
                    k: v
                    for k, v in self._store.items()
                    if now - v.get("ts", 0) <= self._ttl
                }
            except (json.JSONDecodeError, OSError):
                self._store = {}

    def _save(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._store, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self._file)

    def _evict_if_needed(self):
        if len(self._store) <= MAX_ENTRIES:
            return
        sorted_items = sorted(
            self._store.items(), key=lambda x: x[1].get("ts", 0), reverse=True
        )
        self._store = dict(sorted_items[:MAX_ENTRIES])


# ── Module-level singleton ──────────────────────────────────────────────

_cache: SemanticCache | None = None


def get_cache() -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache
