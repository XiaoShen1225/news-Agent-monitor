"""Tests for cosine similarity clustering."""

import pytest
from agents.clustering import _cosine_sim, cluster_items


class TestCosineSim:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert _cosine_sim(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_sim([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert _cosine_sim([0.0, 0.0], [1.0, 2.0]) == 0.0
        assert _cosine_sim([1.0, 2.0], [0.0, 0.0]) == 0.0

    def test_partial_similarity(self):
        sim = _cosine_sim([1.0, 1.0], [1.0, 2.0])
        assert 0.9 < sim < 1.0

    def test_empty_vectors(self):
        assert _cosine_sim([], []) == 0.0


class TestClusterItems:
    def test_empty_items(self):
        result = cluster_items([], None)
        assert result == []

    def test_single_item(self):
        result = cluster_items([{"title": "test"}], None)
        assert result == []

    def test_no_vector_store(self):
        items = [
            {"title": "a", "site_name": "s1"},
            {"title": "b", "site_name": "s2"},
        ]
        result = cluster_items(items, None)
        assert result == []


class FakeVectorStore:
    """VectorStore stub that returns predefined embeddings."""

    def __init__(self, embeddings_map=None):
        self._map = embeddings_map or {}

    @property
    def _ef(self):
        return lambda titles: [self._map.get(t, None) for t in titles]


class TestClusterWithEmbeddings:
    def test_two_similar_items_cluster(self):
        vs = FakeVectorStore(
            {
                "华为发布新手机": [0.9, 0.1, 0.0],
                "华为 Mate 系列新品发布": [0.85, 0.15, 0.0],
            }
        )
        items = [
            {"title": "华为发布新手机", "site_name": "baidu_news", "tag": "科技"},
            {
                "title": "华为 Mate 系列新品发布",
                "site_name": "sina_news",
                "tag": "科技",
            },
        ]
        result = cluster_items(items, vs, threshold=0.8, min_cluster_size=2)
        assert len(result) == 1
        assert result[0]["size"] == 2
        assert len(result[0]["sites"]) == 2

    def test_dissimilar_items_no_cluster(self):
        vs = FakeVectorStore(
            {
                "科技新闻": [0.9, 0.1, 0.0],
                "体育新闻": [-0.5, 0.8, 0.3],
            }
        )
        items = [
            {"title": "科技新闻", "site_name": "s1", "tag": "科技"},
            {"title": "体育新闻", "site_name": "s2", "tag": "体育"},
        ]
        result = cluster_items(items, vs, threshold=0.8, min_cluster_size=2)
        assert len(result) == 0

    def test_min_cluster_size(self):
        vs = FakeVectorStore(
            {
                "a": [1.0, 0.0],
                "b": [0.95, 0.05],
                "c": [-0.5, 0.8],
            }
        )
        items = [
            {"title": "a", "site_name": "s1"},
            {"title": "b", "site_name": "s2"},
            {"title": "c", "site_name": "s3"},
        ]
        # With min_cluster_size=3, the isolated item 'c' prevents any cluster
        result = cluster_items(items, vs, threshold=0.8, min_cluster_size=3)
        assert len(result) == 0

    def test_tags_collected(self):
        vs = FakeVectorStore(
            {
                "AI 突破": [1.0, 0.0],
                "人工智能新进展": [0.9, 0.1],
            }
        )
        items = [
            {"title": "AI 突破", "site_name": "s1", "tag": "科技"},
            {"title": "人工智能新进展", "site_name": "s2", "tag": "AI"},
        ]
        result = cluster_items(items, vs, threshold=0.8)
        assert len(result) == 1
        assert "科技" in result[0]["tags"]
        assert "AI" in result[0]["tags"]
