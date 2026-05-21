"""Tests for AnalyzerAgent: diff algorithm, tag distribution, trend computation."""

import pytest
from agents.analyzer import AnalyzerAgent


class FakeDataStore:
    """Minimal DataStore stub for AnalyzerAgent tests."""
    def __init__(self, snapshots=None):
        self._snapshots = snapshots or []

    def get_last_snapshot(self, site_name):
        if self._snapshots:
            return self._snapshots[-1]
        return None

    def get_all_snapshots(self, site_name):
        return self._snapshots


@pytest.fixture
def agent():
    config = {"llm": {"api_key": "test", "model": "glm-4-flash"}}
    return AnalyzerAgent(config)


@pytest.fixture
def agent_with_store():
    config = {"llm": {"api_key": "test", "model": "glm-4-flash"}}
    store = FakeDataStore([{
        "items": [
            {"title": "Old News A", "url": "/a", "tag": "科技"},
            {"title": "Old News B", "url": "/b", "tag": "国内"},
            {"title": "Common News", "url": "/c", "tag": "娱乐"},
        ],
        "items_count": 3,
        "timestamp": "2026-05-20T10:00:00",
    }])
    return AnalyzerAgent(config, data_store=store)


class TestDiff:
    def test_new_items(self, agent):
        prev = [{"title": "A"}]
        curr = [{"title": "A"}, {"title": "B"}]
        new, removed, modified = agent._diff_items(prev, curr)
        assert len(new) == 1
        assert new[0]["title"] == "B"
        assert len(removed) == 0

    def test_removed_items(self, agent):
        prev = [{"title": "A"}, {"title": "B"}]
        curr = [{"title": "A"}]
        new, removed, modified = agent._diff_items(prev, curr)
        assert len(removed) == 1
        assert removed[0]["title"] == "B"
        assert len(new) == 0

    def test_modified_items(self, agent):
        prev = [{"title": "A", "tag": "科技"}]
        curr = [{"title": "A", "tag": "财经"}]
        new, removed, modified = agent._diff_items(prev, curr)
        assert len(modified) == 1
        assert modified[0]["title"] == "A"

    def test_no_changes(self, agent):
        prev = [{"title": "A", "tag": "科技"}]
        curr = [{"title": "A", "tag": "科技"}]
        new, removed, modified = agent._diff_items(prev, curr)
        assert len(new) == 0
        assert len(removed) == 0
        assert len(modified) == 0

    def test_empty_previous(self, agent):
        new, removed, modified = agent._diff_items([], [{"title": "X"}])
        assert len(new) == 1
        assert len(removed) == 0


class TestTagDistribution:
    def test_basic(self, agent):
        items = [
            {"tag": "科技"}, {"tag": "科技"}, {"tag": "娱乐"}
        ]
        dist = agent._tag_distribution(items)
        assert dist["科技"] == 2
        assert dist["娱乐"] == 1

    def test_missing_tag_defaults(self, agent):
        items = [{"title": "X"}]
        dist = agent._tag_distribution(items)
        assert dist.get("其他", 0) == 1

    def test_sorted_desc(self, agent):
        items = [{"tag": "A"}, {"tag": "B"}, {"tag": "B"}]
        dist = agent._tag_distribution(items)
        keys = list(dist.keys())
        assert keys[0] == "B"
        assert keys[1] == "A"


class TestTrendComputation:
    def test_insufficient_data(self, agent):
        # Without a store, _compute_trends returns empty dict
        trends = agent._compute_trends("test", [{"tag": "A"}])
        assert trends == {}

    def test_with_store_data(self, agent_with_store):
        items = [{"title": "New News C", "url": "/c", "tag": "科技"}]
        report = agent_with_store.run(items, "test", "fake_hash")
        assert report["is_first_run"] is False
        assert report["previous_count"] == 3
        assert report["current_count"] == 1


class TestRun:
    def test_first_run(self, agent):
        items = [{"title": "A", "url": "/a", "tag": "科技"}]
        report = agent.run(items, "test", "hash123")
        assert report["is_first_run"] is True
        assert report["has_changes"] is True
        assert report["current_count"] == 1

    def test_run_with_changes(self, agent_with_store):
        items = [
            {"title": "Common News", "url": "/c", "tag": "娱乐"},
            {"title": "New Item", "url": "/n", "tag": "科技"},
        ]
        report = agent_with_store.run(items, "test", "new_hash")
        assert report["has_changes"] is True
        assert report["total_changes"] > 0
