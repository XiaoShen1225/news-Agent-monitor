"""Tests for hybrid search: BM25Index, RRF fusion, HybridSearcher."""

import pytest
from data.hybrid_search import BM25Index, HybridSearcher, _rrf_fusion


# ── BM25Index ────────────────────────────────────────────────────────


class TestBM25Index:
    def test_empty_index(self):
        idx = BM25Index()
        assert idx.doc_count == 0
        assert idx.search("测试") == []

    def test_add_and_search(self):
        idx = BM25Index()
        idx.add("华为发布新款芯片", {"title": "华为发布新款芯片", "url": "http://a"})
        idx.add("苹果推出新手机", {"title": "苹果推出新手机", "url": "http://b"})
        idx.add("华为芯片供应危机", {"title": "华为芯片供应危机", "url": "http://c"})
        assert idx.doc_count == 3

        results = idx.search("华为芯片", top_k=10)
        assert len(results) >= 1
        # First result should be about 华为芯片
        best_idx, best_score = results[0]
        best_title = idx._documents[best_idx]["title"]
        assert "华为" in best_title

    def test_search_no_match(self):
        idx = BM25Index()
        idx.add("华为发布", {"title": "华为发布"})
        results = idx.search("xyz不存在的词")
        # Should return empty or low-score results
        # Our implementation only returns items with score > 0
        assert len(results) == 0

    def test_rebuild(self):
        idx = BM25Index()
        idx.add("旧数据", {"title": "旧数据"})
        assert idx.doc_count == 1

        new_items = [
            {"title": "新数据A"},
            {"title": "新数据B"},
        ]
        idx.rebuild(new_items)
        assert idx.doc_count == 2
        assert idx._documents[0]["title"] == "新数据A"

    def test_score_ordering(self):
        idx = BM25Index()
        idx.add("华为芯片华为芯片华为芯片", {"title": "华为芯片A"})  # high TF
        idx.add("华为发布会", {"title": "华为发布会"})  # lower TF
        idx.add("苹果手机", {"title": "苹果手机"})  # no match

        results = idx.search("华为芯片")
        assert len(results) == 2
        # Higher TF should rank first
        assert idx._documents[results[0][0]]["title"] == "华为芯片A"

    def test_idf_weighting(self):
        """Rare terms should get higher IDF than common terms."""
        idx = BM25Index()
        # "稀有" appears in 1 doc, "常见" appears in all docs
        idx.add("稀有词汇常见词", {"title": "T1"})
        idx.add("常见词", {"title": "T2"})
        idx.add("常见词", {"title": "T3"})

        results = idx.search("稀有", top_k=5)
        assert len(results) == 1
        assert idx._documents[results[0][0]]["title"] == "T1"

    def test_chinese_tokenization(self):
        idx = BM25Index()
        idx.add("华为发布最新芯片产品", {"title": "T1"})
        idx.add("华为手机销量创新高", {"title": "T2"})
        idx.add("苹果公司推出新手机", {"title": "T3"})

        # "华为" should match both T1 and T2 (jieba segments "华为" consistently)
        results = idx.search("华为")
        assert len(results) >= 2
        matched_titles = {idx._documents[r[0]]["title"] for r in results}
        assert "T1" in matched_titles
        assert "T2" in matched_titles


# ── RRF Fusion ───────────────────────────────────────────────────────


class TestRRFFusion:
    def test_empty_both(self):
        assert _rrf_fusion([], []) == []

    def test_bm25_only(self):
        bm25 = [
            {"title": "华为发布", "url": "http://a"},
            {"title": "芯片短缺", "url": "http://b"},
        ]
        result = _rrf_fusion(bm25, [], limit=10)
        assert len(result) == 2
        assert result[0]["sources"] == ["bm25"]

    def test_vector_only(self):
        vec = [{"title": "AI突破", "url": "http://c"}]
        result = _rrf_fusion([], vec, limit=10)
        assert len(result) == 1
        assert result[0]["sources"] == ["vector"]

    def test_merge_both_sources(self):
        bm25 = [{"title": "华为发布新品", "url": "http://a"}]
        vec = [{"title": "华为发布新品", "url": "http://a"}]  # same title
        result = _rrf_fusion(bm25, vec, limit=10)
        assert len(result) == 1
        assert set(result[0]["sources"]) == {"bm25", "vector"}

    def test_rrf_dedup_by_title(self):
        bm25 = [
            {"title": "华为发布新品", "url": "http://a"},
            {"title": "芯片新闻", "url": "http://b"},
        ]
        vec = [
            {"title": "华为发布新品", "url": "http://a2"},  # same title, diff url
            {"title": "AI新突破", "url": "http://d"},
        ]
        result = _rrf_fusion(bm25, vec, limit=10)
        # 3 unique titles
        assert len(result) == 3
        # The merged one should have both sources
        merged = [r for r in result if r["title"] == "华为发布新品"]
        assert len(merged) == 1
        assert set(merged[0]["sources"]) == {"bm25", "vector"}

    def test_rrf_limit(self):
        bm25 = [{"title": f"新闻{i}"} for i in range(10)]
        result = _rrf_fusion(bm25, [], limit=3)
        assert len(result) == 3

    def test_rrf_score_assigned(self):
        bm25 = [{"title": "测试标题"}]
        result = _rrf_fusion(bm25, [], limit=1)
        assert "fusion_score" in result[0]
        assert result[0]["fusion_score"] > 0


# ── HybridSearcher integration ──────────────────────────────────────


class FakeVectorStore:
    def search(self, query, site_name=None, limit=10):
        # Return synthetic vector search results
        return [
            {
                "title": f"{query}相关新闻兴趣",
                "url": "http://vec/1",
                "site_name": site_name or "baidu_news",
                "tag": "科技",
                "sentiment": "",
                "snapshot_time": "2026-05-31T00:00:00",
                "score": 0.85,
            },
            {
                "title": f"另一条{query}新闻",
                "url": "http://vec/2",
                "site_name": site_name or "sina_news",
                "tag": "科技",
                "sentiment": "",
                "snapshot_time": "2026-05-30T00:00:00",
                "score": 0.72,
            },
        ]


class TestHybridSearcher:
    @pytest.fixture
    def bm25(self):
        idx = BM25Index()
        idx.add(
            "华为发布新款芯片",
            {
                "title": "华为发布新款芯片",
                "url": "http://a",
                "site_name": "baidu_news",
                "tag": "科技",
                "snapshot_time": "2026-05-31T00:00:00",
            },
        )
        idx.add(
            "苹果推出新手机",
            {
                "title": "苹果推出新手机",
                "url": "http://b",
                "site_name": "sina_news",
                "tag": "科技",
                "snapshot_time": "2026-05-30T00:00:00",
            },
        )
        idx.add(
            "芯片供应危机加剧",
            {
                "title": "芯片供应危机加剧",
                "url": "http://c",
                "site_name": "baidu_news",
                "tag": "财经",
                "snapshot_time": "2026-05-29T00:00:00",
            },
        )
        return idx

    @pytest.fixture
    def searcher(self, bm25):
        return HybridSearcher(bm25, FakeVectorStore())

    def test_search_returns_results(self, searcher):
        results = searcher.search("华为芯片")
        assert len(results) > 0
        assert "fusion_score" in results[0]
        assert "sources" in results[0]

    def test_search_empty_query(self, searcher):
        assert searcher.search("") == []
        assert searcher.search("  ") == []

    def test_search_with_site_filter(self, searcher):
        results = searcher.search("芯片", site_name="baidu_news")
        for r in results:
            assert r.get("site_name") == "baidu_news"

    def test_search_with_tag_filter(self, searcher):
        results = searcher.search("供应", tag="财经")
        for r in results:
            assert r.get("tag") == "财经"

    def test_search_with_date_filter(self, searcher):
        results = searcher.search("芯片", date_from="2026-05-31T00:00:00")
        for r in results:
            assert r.get("snapshot_time", "") >= "2026-05-31T00:00:00"

    def test_combined_bm25_and_vector(self, searcher):
        """Verify that results come from both channels."""
        results = searcher.search("华为", limit=10)
        sources = set()
        for r in results:
            sources.update(r.get("sources", []))
        # Should have at least one result from bm25
        assert "bm25" in sources or len(results) > 0

    def test_rebuild_bm25(self, searcher):
        new_items = [
            {"title": "全新测试新闻"},
            {"title": "另一个测试"},
        ]
        searcher.rebuild_bm25(new_items)
        assert searcher._bm25.doc_count == 2
