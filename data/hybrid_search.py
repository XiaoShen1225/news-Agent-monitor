"""Hybrid search: BM25 keyword index + ChromaDB vector semantic search + RRF fusion.

BM25Index: pure-Python inverted index with jieba Chinese word segmentation.
HybridSearcher: combines BM25 precision with vector semantic recall via RRF.
"""

import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)


# ── BM25 Index ──────────────────────────────────────────────────────


class BM25Index:
    """Pure-Python BM25 inverted index with jieba tokenization for Chinese.

    Thread-safe for reads; writes (add) should be serialized.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._documents: list[dict] = []
        self._doc_tokens: list[list[str]] = []
        self._doc_freqs: dict[str, int] = defaultdict(int)
        self._avgdl: float = 0.0
        self._dirty: bool = False

    @property
    def doc_count(self) -> int:
        return len(self._documents)

    def add(self, title: str, item: dict):
        """Add or update a document in the index."""
        import jieba

        tokens = [t for t in jieba.cut(title) if t.strip()]
        if not tokens:
            return

        self._documents.append(item)
        self._doc_tokens.append(tokens)
        for t in set(tokens):
            self._doc_freqs[t] += 1
        self._dirty = True

    def rebuild(self, items: list[dict]):
        """Bulk-load documents into the index, replacing all existing data."""
        import jieba

        self._documents.clear()
        self._doc_tokens.clear()
        self._doc_freqs.clear()

        for item in items:
            title = item.get("title", "")
            tokens = [t for t in jieba.cut(title) if t.strip()]
            if not tokens:
                continue
            self._documents.append(item)
            self._doc_tokens.append(tokens)
            for t in set(tokens):
                self._doc_freqs[t] += 1
        self._dirty = True
        logger.info("[BM25] Index rebuilt: %d documents", len(self._documents))

    def _update_stats(self):
        if not self._dirty:
            return
        total_len = sum(len(tokens) for tokens in self._doc_tokens)
        self._avgdl = total_len / max(len(self._doc_tokens), 1)
        self._dirty = False

    def search(self, query: str, top_k: int = 50) -> list[tuple[int, float]]:
        """Search and return [(doc_index, bm25_score), ...] sorted by score descending."""
        if not self._doc_tokens:
            return []
        import jieba

        self._update_stats()
        query_tokens = [t for t in jieba.cut(query) if t.strip()]
        if not query_tokens:
            return []

        N = len(self._doc_tokens)
        scores: list[tuple[int, float]] = []

        for idx, tokens in enumerate(self._doc_tokens):
            score = 0.0
            dl = len(tokens)
            for qt in query_tokens:
                tf = tokens.count(qt)
                if tf == 0:
                    continue
                df = self._doc_freqs.get(qt, 0)
                if df == 0:
                    continue
                # BM25 IDF
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                # BM25 term score
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * dl / self._avgdl)
                score += idf * numerator / denominator
            if score > 0:
                scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ── RRF Fusion ───────────────────────────────────────────────────────


def _rrf_fusion(
    bm25_ranked: list[dict],
    vector_ranked: list[dict],
    k: int = 60,
    limit: int = 20,
) -> list[dict]:
    """Reciprocal Rank Fusion.

    score(d) = Σ 1/(k + rank_i(d))

    Results deduplicated by title. Each result annotated with which
    channel(s) contributed.
    """
    scores: dict[str, dict] = {}  # title → {item, score, sources}

    for rank, item in enumerate(bm25_ranked, start=1):
        title = item.get("title", "")
        key = title.lower().strip()
        rrf = 1.0 / (k + rank)
        if key in scores:
            scores[key]["score"] += rrf
            scores[key]["sources"].add("bm25")
        else:
            scores[key] = {"item": item, "score": rrf, "sources": {"bm25"}}

    for rank, item in enumerate(vector_ranked, start=1):
        title = item.get("title", "")
        key = title.lower().strip()
        rrf = 1.0 / (k + rank)
        if key in scores:
            scores[key]["score"] += rrf
            scores[key]["sources"].add("vector")
        else:
            scores[key] = {"item": item, "score": rrf, "sources": {"vector"}}

    merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    results = []
    for entry in merged[:limit]:
        item = entry["item"]
        item["fusion_score"] = round(entry["score"], 6)
        item["sources"] = sorted(entry["sources"])
        results.append(item)

    return results


# ── Hybrid Searcher ─────────────────────────────────────────────────


class HybridSearcher:
    """Combines BM25 keyword search with ChromaDB vector semantic search."""

    def __init__(
        self,
        bm25_index: BM25Index,
        vector_store,
        config: dict | None = None,
    ):
        self._bm25 = bm25_index
        self._vector = vector_store
        cfg = config or {}
        self._rrf_k = cfg.get("rrf_k", 60)
        self._bm25_top_k = cfg.get("bm25_top_k", 50)
        self._vector_top_k = cfg.get("vector_top_k", 50)

    def search(
        self,
        query: str,
        site_name: str | None = None,
        tag: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Hybrid search: BM25 + Vector → RRF fusion.

        BM25 covers exact keyword recall; Vector covers semantic recall.
        RRF merges the two ranked lists without parameter tuning.
        """
        query = query.strip()
        if not query:
            return []

        # ── BM25 channel ──────────────────────────────────────────
        bm25_hits = self._bm25.search(query, top_k=self._bm25_top_k)
        bm25_items = [self._bm25._documents[idx] for idx, _ in bm25_hits]
        bm25_items = self._apply_filters(bm25_items, site_name, tag, date_from, date_to)

        # ── Vector channel ────────────────────────────────────────
        try:
            vector_raw = self._vector.search(
                query, site_name=site_name, limit=self._vector_top_k
            )
        except Exception:
            logger.warning("[HybridSearch] Vector search failed, using BM25 only")
            vector_raw = []
        vector_items = self._apply_filters(
            vector_raw, site_name, tag, date_from, date_to
        )

        # ── RRF fusion ────────────────────────────────────────────
        fused = _rrf_fusion(
            bm25_items, vector_items, k=self._rrf_k, limit=max(limit * 3, 60)
        )

        logger.info(
            "[HybridSearch] query='%s' → bm25=%d, vector=%d, fused=%d",
            query[:60],
            len(bm25_items),
            len(vector_items),
            len(fused),
        )
        return fused[:limit]

    @staticmethod
    def _apply_filters(
        items: list[dict],
        site_name: str | None,
        tag: str | None,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict]:
        """Post-filter results by metadata fields."""
        filtered = []
        for item in items:
            if site_name and item.get("site_name", "") != site_name:
                continue
            if tag and item.get("tag", "") != tag:
                continue
            if date_from or date_to:
                ts = item.get("snapshot_time", "")
                if date_from and ts < date_from:
                    continue
                if date_to and ts > date_to:
                    continue
            filtered.append(item)
        return filtered

    def rebuild_bm25(self, items: list[dict]):
        """Rebuild BM25 index from a fresh batch of items."""
        self._bm25.rebuild(items)
