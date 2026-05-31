"""Tests for DeepAnalyzer agent."""

import pytest
from agents.deep_analyzer import DeepAnalyzer


@pytest.fixture
def agent():
    config = {
        "llm": {"api_key": "test", "model": "glm-4-flash"},
        "deep_analysis": {
            "cluster_similarity_threshold": 0.75,
            "min_event_items": 2,
            "entity_batch_size": 50,
            "timeline_lookback_snapshots": 20,
        },
    }
    return DeepAnalyzer(config)


class FakeVectorStore:
    def __init__(self, embeddings_map=None):
        self._map = embeddings_map or {}

    @property
    def _ef(self):
        return lambda titles: [self._map.get(t, None) for t in titles]


class TestDeepAnalyzerInit:
    def test_name(self, agent):
        assert agent.name == "DeepAnalyzer"

    def test_config_read(self, agent):
        assert agent._deep_cfg["cluster_similarity_threshold"] == 0.75
        assert agent._deep_cfg["min_event_items"] == 2
        assert agent._deep_cfg["entity_batch_size"] == 50

    def test_provider_lazy_init(self, agent):
        assert agent._provider is None

    def test_default_config(self):
        agent = DeepAnalyzer({})
        assert agent._deep_cfg == {}


class TestClusterEvents:
    @pytest.mark.asyncio
    async def test_empty_items(self, agent):
        result = await agent.cluster_events([], None)
        assert result == []

    @pytest.mark.asyncio
    async def test_single_item(self, agent):
        result = await agent.cluster_events([{"title": "test"}], None)
        assert result == []

    @pytest.mark.asyncio
    async def test_with_embeddings_no_llm(self, agent):
        """Clustering should work, but event naming will fall back (no LLM key)."""
        vs = FakeVectorStore(
            {
                "华为发布会": [0.9, 0.1, 0.0],
                "华为 Mate 新品": [0.85, 0.15, 0.0],
            }
        )
        items = [
            {
                "title": "华为发布会",
                "site_name": "baidu_news",
                "tag": "科技",
                "url": "http://a",
            },
            {
                "title": "华为 Mate 新品",
                "site_name": "sina_news",
                "tag": "科技",
                "url": "http://b",
            },
        ]
        # Will attempt LLM naming, fall back gracefully
        result = await agent.cluster_events(items, vs)
        assert len(result) >= 1
        assert result[0]["size"] == 2
        assert "event_id" in result[0]
        assert "event_name" in result[0]


class TestExtractEntities:
    @pytest.mark.asyncio
    async def test_empty_items(self, agent):
        result = await agent.extract_entities([])
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_with_llm_fallback(self, agent):
        """Should handle LLM failure gracefully (no real API key)."""
        items = [
            {"title": "华为发布新款芯片"},
            {"title": "北京国际科技展开幕"},
        ]
        # Will attempt LLM, fall back gracefully
        result = await agent.extract_entities(items)
        # Either gets entities or empty list (LLM fail → fallback "[]")
        assert isinstance(result, list)


class TestBuildTimeline:
    @pytest.mark.asyncio
    async def test_empty_items(self, agent):
        result = await agent.build_timeline("test", [], None)
        assert result["event_name"] == "test"
        assert result["timeline"] == []

    @pytest.mark.asyncio
    async def test_with_items(self, agent):
        items = [
            {
                "title": "事件1",
                "site_name": "s1",
                "snapshot_time": "2026-05-01T10:00:00",
                "url": "http://a",
            },
            {
                "title": "事件2",
                "site_name": "s2",
                "snapshot_time": "2026-05-02T12:00:00",
                "url": "http://b",
            },
        ]
        result = await agent.build_timeline("测试事件", items, None)
        assert result["event_name"] == "测试事件"
        assert len(result["timeline"]) == 2
        assert result["item_count"] == 2
        # Timeline should be sorted by time
        assert result["timeline"][0]["site"] == "s1"
        assert result["timeline"][1]["site"] == "s2"
