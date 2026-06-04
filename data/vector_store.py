"""Vector store for news items using ChromaDB + sentence-transformers embeddings."""

import logging
import os
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

logger = logging.getLogger(__name__)

# High-quality Chinese embedding model (1792-dim, MTEB-zh top-tier)
_EMBEDDING_MODEL = "infgrad/stella-base-zh-v3-1792d"
_CACHE_DIR = str(Path(Path.home(), ".cache", "torch", "sentence_transformers"))


def _load_embedding_model():
    """Load SentenceTransformer from local cache only, no network."""
    # Must be set BEFORE importing sentence_transformers
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        _EMBEDDING_MODEL,
        cache_folder=_CACHE_DIR,
        local_files_only=True,
    )


def _make_embedding_fn(model):
    """Build a chromadb-compatible embedding function from a loaded model."""
    from chromadb.api.types import EmbeddingFunction

    class _STEmbeddingFn(EmbeddingFunction):
        def __call__(self, texts):
            return model.encode(list(texts), normalize_embeddings=True).tolist()

    return _STEmbeddingFn()


class VectorStore:
    """Manages a ChromaDB collection for semantic search over news items."""

    def __init__(self, persist_dir: str = "data/vector_db"):
        import chromadb

        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._ef = _make_embedding_fn(_load_embedding_model())
        self._collection = None
        self._collection_count = None

        self._model_id_file = self.persist_dir / ".model_id"
        self._migrate_if_needed()

    def _migrate_if_needed(self):
        """Reset collection if embedding model changed (dimensions differ)."""
        prev_model = ""
        if self._model_id_file.exists():
            prev_model = self._model_id_file.read_text().strip()
        if prev_model and prev_model != _EMBEDDING_MODEL:
            logger.info(
                "Embedding model changed (%s → %s), rebuilding vector index",
                prev_model,
                _EMBEDDING_MODEL,
            )
            try:
                self._client.delete_collection("news_items")
            except Exception:
                pass
        self._model_id_file.write_text(_EMBEDDING_MODEL)

    @property
    def collection(self):
        if self._collection is None:
            name = "news_items"
            try:
                self._collection = self._client.get_collection(
                    name, embedding_function=self._ef
                )
                self._collection_count = self._collection.count()
            except Exception:
                self._collection = self._client.create_collection(
                    name, embedding_function=self._ef
                )
                self._collection_count = 0
        return self._collection

    # ── add ───────────────────────────────────────────────────────────

    def add_items(self, items: list, site_name: str):
        """Add news items to the vector store. Deduplicates by title+site.

        Each item should have: title, url, tag, snapshot_time.
        """
        if not items:
            return

        ids = []
        documents = []
        metadatas = []
        for item in items:
            title = item.get("title", "")
            if not title:
                continue
            doc_id = f"{site_name}:{title}"
            ids.append(doc_id)
            documents.append(title)
            metadatas.append(
                {
                    "site_name": site_name,
                    "url": item.get("url", ""),
                    "tag": item.get("tag", ""),
                    "sentiment": item.get("sentiment", ""),
                    "snapshot_time": item.get("snapshot_time", ""),
                }
            )

        if not ids:
            return

        try:
            col = self.collection
            col.upsert(ids=ids, documents=documents, metadatas=metadatas)
            self._collection_count = col.count()
        except Exception as e:
            logger.warning("VectorStore add_items failed: %s", e)

    # ── search ────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        site_name: str = None,
        limit: int = 10,
    ) -> list:
        """Semantic search for news items. Returns list of dicts."""
        try:
            col = self.collection
            where = {"site_name": site_name} if site_name else None
            results = col.query(
                query_texts=[query],
                n_results=limit,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.warning("VectorStore search failed: %s", e)
            return []

        items = []
        if results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                items.append(
                    {
                        "title": results["documents"][0][i],
                        "site_name": results["metadatas"][0][i].get("site_name", ""),
                        "url": results["metadatas"][0][i].get("url", ""),
                        "tag": results["metadatas"][0][i].get("tag", ""),
                        "sentiment": results["metadatas"][0][i].get("sentiment", ""),
                        "snapshot_time": results["metadatas"][0][i].get(
                            "snapshot_time", ""
                        ),
                        "score": round(1 - results["distances"][0][i], 4)
                        if results.get("distances")
                        else 0,
                    }
                )
        return items

    # ── stats ─────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        if self._collection_count is None:
            try:
                self._collection_count = self.collection.count()
            except Exception:
                return 0
        return self._collection_count

    def reset(self):
        """Delete and recreate the collection."""
        try:
            self._client.delete_collection("news_items")
        except Exception:
            pass
        self._collection = None
        self._collection_count = None
        logger.info("VectorStore reset complete")
