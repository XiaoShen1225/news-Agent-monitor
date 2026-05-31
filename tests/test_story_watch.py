"""Tests for StoryWatchStore lifecycle management and matching."""

import os
import tempfile
from datetime import datetime, timedelta

import pytest
from data.story_watch import StoryWatchStore, _cosine_sim, _is_near_duplicate, _now_iso


@pytest.fixture
def store():
    td = tempfile.mkdtemp()
    path = os.path.join(td, "test_stories.json")
    s = StoryWatchStore(file_path=path)
    yield s
    # Cleanup
    try:
        os.remove(path)
        os.rmdir(td)
    except Exception:
        pass


class TestStoryCRUD:
    def test_add_story(self, store):
        r = store.add_story("华为发布会", url="http://example.com/1")
        assert r["ok"] is True
        assert r["story_id"].startswith("story_")
        assert len(store._data["stories"]) == 1
        assert store._data["stories"][0]["status"] == "active"

    def test_add_empty_title_fails(self, store):
        r = store.add_story("")
        assert r["ok"] is False

    def test_add_duplicate_title(self, store):
        store.add_story("华为发布会")
        r = store.add_story("华为发布会")
        assert r["ok"] is True
        assert "已在追踪" in r["msg"]

    def test_remove_by_id(self, store):
        r = store.add_story("测试事件")
        sid = r["story_id"]
        r2 = store.remove_story(story_id=sid)
        assert r2["ok"] is True
        assert len(store._data["stories"]) == 0

    def test_remove_by_title(self, store):
        store.add_story("测试事件")
        r = store.remove_story(title="测试事件")
        assert r["ok"] is True

    def test_remove_not_found(self, store):
        r = store.remove_story(story_id="nonexistent")
        assert r["ok"] is False

    def test_complete_story(self, store):
        r = store.add_story("测试事件")
        r2 = store.complete_story(r["story_id"])
        assert r2["ok"] is True
        assert store._data["stories"][0]["status"] == "completed"

    def test_list_stories(self, store):
        store.add_story("故事A")
        store.add_story("故事B")
        stories = store.list_stories()
        assert len(stories) == 2

    def test_list_filter_by_status(self, store):
        r = store.add_story("故事A")
        store.complete_story(r["story_id"])
        store.add_story("故事B")
        active = store.list_stories(status="active")
        completed = store.list_stories(status="completed")
        assert len(active) == 1
        assert len(completed) == 1


class TestLifecycle:
    def test_never_matched_auto_dormant(self, store):
        """Story that never matches should go dormant after dormant_after_days."""
        store._data["config"]["dormant_after_days"] = 0  # immediate
        store.add_story("旧故事")
        # Backdate created_at so auto-dormant triggers
        old_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        store._data["stories"][0]["created_at"] = old_date
        store._save()
        stories = store.list_stories()
        # Should be moved to dormant
        assert all(s["status"] == "dormant" for s in stories)

    def test_dormant_story_removed(self, store):
        """Dormant story past remove_dormant_after_days should be cleaned."""
        store._data["config"]["dormant_after_days"] = 0
        store._data["config"]["remove_dormant_after_days"] = 0
        # Create a story, then backdate both dates to force removal
        store.add_story("旧故事")
        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%S")
        store._data["stories"][0]["status"] = "dormant"
        store._data["stories"][0]["last_match_at"] = old_date
        store._data["stories"][0]["created_at"] = old_date
        store._save()
        stories = store.list_stories()
        assert len(stories) == 0

    def test_reactivate_story(self, store):
        """Reactivation moves dormant back to active."""
        r = store.add_story("休眠故事")
        sid = r["story_id"]
        store._data["stories"][0]["status"] = "dormant"
        store._save()
        r2 = store.reactivate_story(sid)
        assert r2["ok"] is True
        assert store._data["stories"][0]["status"] == "active"

    def test_get_dormant_stories(self, store):
        store.add_story("活跃故事")
        store.add_story("休眠故事")
        store._data["stories"][1]["status"] = "dormant"
        store._save()
        dormant = store.get_dormant_stories()
        assert len(dormant) == 1


class FakeVectorStore:
    def __init__(self, embeddings_map=None):
        self._map = embeddings_map or {}

    @property
    def _ef(self):
        return lambda titles: [self._map.get(t, None) for t in titles]


class TestMatchNewItems:
    def test_basic_match(self, store):
        vs = FakeVectorStore(
            {
                "华为新品发布后续报道": [0.85, 0.1, -0.05],
                "苹果发布新手机": [-0.5, 0.9, 0.0],
            }
        )
        store.add_story(
            "华为新品发布会召开",
            url="http://a",
            embedding=[0.9, 0.1, 0.0],
        )
        new_items = [
            {
                "title": "华为新品发布后续报道",
                "site_name": "baidu_news",
                "url": "http://b",
            },
            {"title": "苹果发布新手机", "site_name": "sina_news", "url": "http://c"},
        ]
        matches = store.check_new_items(new_items, vs)
        assert len(matches) >= 1
        # The 华为 story should match the first item
        match_titles = [m["item_title"] for m in matches]
        assert "华为新品发布后续报道" in match_titles

    def test_near_duplicate_skipped(self, store):
        """Near-identical title should be skipped (same article, not follow-up)."""
        vs = FakeVectorStore({"华为新品发布会召开": [0.9, 0.1, 0.0]})
        store.add_story(
            "华为新品发布会召开",
            embedding=[0.9, 0.1, 0.0],
        )
        new_items = [
            {
                "title": "华为新品发布会召开",
                "site_name": "sina_news",
                "url": "http://b",
            },
        ]
        matches = store.check_new_items(new_items, vs)
        assert len(matches) == 0

    def test_cooldown_respected(self, store):
        """Second check within cooldown should return empty."""
        vs = FakeVectorStore({"华为后续报道": [0.85, 0.1, 0.0]})
        store.add_story(
            "华为发布会",
            embedding=[0.9, 0.1, 0.0],
        )
        new_items = [
            {"title": "华为后续报道", "site_name": "baidu_news", "url": "http://b"},
        ]
        matches1 = store.check_new_items(new_items, vs)
        assert len(matches1) == 1
        # Immediate re-check should be suppressed by cooldown
        matches2 = store.check_new_items(new_items, vs)
        assert len(matches2) == 0

    def test_no_embedding_story_skipped(self, store):
        """Story without embedding should be skipped in matching."""
        vs = FakeVectorStore({"some title": [0.5, 0.5, 0.0]})
        store.add_story("无嵌入的故事")  # no embedding
        matches = store.check_new_items(
            [{"title": "some title", "site_name": "s1"}], vs
        )
        assert len(matches) == 0

    def test_match_history_recorded(self, store):
        vs = FakeVectorStore({"华为后续": [0.85, 0.1, 0.0]})
        store.add_story(
            "华为发布会",
            embedding=[0.9, 0.1, 0.0],
        )
        new_items = [
            {"title": "华为后续", "site_name": "baidu_news", "url": "http://b"},
        ]
        store.check_new_items(new_items, vs)
        story = store._data["stories"][0]
        assert story["match_count"] == 1
        assert len(story["match_history"]) == 1
        assert story["last_match_at"] is not None


class TestConfig:
    def test_load_config(self, store):
        store.load_config(
            {
                "story_watch": {
                    "similarity_threshold": 0.75,
                    "match_cooldown_hours": 6,
                    "dormant_after_days": 14,
                    "remove_dormant_after_days": 60,
                }
            }
        )
        cfg = store.get_config()
        assert cfg["similarity_threshold"] == 0.75
        assert cfg["match_cooldown_hours"] == 6
        assert cfg["dormant_after_days"] == 14
        assert cfg["remove_dormant_after_days"] == 60

    def test_load_config_defaults(self, store):
        store.load_config({})
        cfg = store.get_config()
        assert "similarity_threshold" in cfg


class TestHelpers:
    def test_cosine_sim_identical(self):
        assert _cosine_sim([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_cosine_sim_orthogonal(self):
        assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_is_near_duplicate_true(self):
        assert _is_near_duplicate("华为发布新品", "华为发布新品") is True

    def test_is_near_duplicate_false(self):
        assert _is_near_duplicate("华为发布新品", "苹果发布新机") is False

    def test_now_iso_format(self):
        ts = _now_iso()
        assert "T" in ts
        assert len(ts) == 19


class TestComputeEmbedding:
    def test_compute_embedding(self, store):
        vs = FakeVectorStore({"测试标题": [0.5, 0.3, 0.2]})
        emb = store.compute_embedding("测试标题", vs)
        assert emb == [0.5, 0.3, 0.2]

    def test_compute_embedding_none(self, store):
        vs = FakeVectorStore({})
        emb = store.compute_embedding("未知标题", vs)
        assert emb is None
