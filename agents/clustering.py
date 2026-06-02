"""Cosine-similarity clustering for news items via VectorStore embeddings."""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def cluster_items(
    items: list[dict],
    vector_store,
    threshold: float = 0.75,
    min_cluster_size: int = 2,
) -> list[dict]:
    """Cluster new items into cross-site event groups.

    Returns list of clusters: [{"items": [...], "sites": [...], "tags": [...]}, ...]
    Only clusters with >= min_cluster_size items are returned.
    """
    if not items or len(items) < min_cluster_size:
        return []

    titles = [it.get("title", "") for it in items]
    embeddings = _get_embeddings(titles, vector_store)
    if not embeddings or len(embeddings) < min_cluster_size:
        return []

    n = len(embeddings)
    # Compute pairwise cosine similarity
    # Build adjacency list via union-find for efficiency
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Only compare upper triangle
    for i in range(n):
        ei = embeddings[i]
        if ei is None:
            continue
        for j in range(i + 1, n):
            ej = embeddings[j]
            if ej is None:
                continue
            sim = _cosine_sim(ei, ej)
            if sim >= threshold:
                union(i, j)

    # Group by root
    groups = defaultdict(list)
    for i in range(n):
        if embeddings[i] is not None:
            groups[find(i)].append(i)

    clusters = []
    for indices in groups.values():
        if len(indices) < min_cluster_size:
            continue
        cluster_items = [items[i] for i in indices]
        sites = list(
            {it.get("site_name", "") for it in cluster_items if it.get("site_name")}
        )
        tags = list({it.get("tag", "") for it in cluster_items if it.get("tag")})
        clusters.append(
            {
                "items": cluster_items,
                "sites": sites,
                "tags": tags,
                "size": len(cluster_items),
            }
        )

    clusters.sort(key=lambda c: c["size"], reverse=True)
    logger.info("[Clustering] Found %d event clusters from %d items", len(clusters), n)
    return clusters


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_embeddings(titles: list[str], vector_store) -> list[list[float] | None]:
    """Get embeddings for a list of titles from the VectorStore's embedding function."""
    if vector_store is None:
        return [None] * len(titles)
    try:
        ef = vector_store._ef
        embeddings = ef(titles)
        return [list(e) if e is not None else None for e in embeddings]
    except Exception as e:
        logger.warning("[Clustering] Failed to get embeddings: %s", e)
        return [None] * len(titles)
