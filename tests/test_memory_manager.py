"""MemoryManager tests — funnel architecture: collect → jieba → LLM → profile."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def tmp_memory_dir():
    with tempfile.TemporaryDirectory() as d:
        old_cwd = os.getcwd()
        os.chdir(d)
        Path("data/memory").mkdir(parents=True, exist_ok=True)
        try:
            yield Path(d)
        finally:
            os.chdir(old_cwd)


@pytest.fixture
def mock_track_store():
    ts = MagicMock()
    ts.get_recent.return_value = []
    ts.expire_ttl_l0.return_value = None
    ts.purge_expired_l0.return_value = None
    return ts


@pytest.fixture
def memory_manager(mock_track_store, tmp_memory_dir):
    from agents.memory_manager import MemoryManager

    return MemoryManager(mock_track_store, {"model": "test-model"})


# ═══════════════════════════════════════════════════════════════════════════
# Keyword cloud extraction (jieba)
# ═══════════════════════════════════════════════════════════════════════════


class TestKeywordCloud:
    def test_extracts_chinese_keywords(self):
        from agents.memory_manager import _extract_keyword_cloud

        cloud = _extract_keyword_cloud(
            ["人工智能和机器学习是未来趋势，深度学习改变世界"], top_k=10
        )
        keywords = [c["keyword"] for c in cloud]
        assert (
            "人工智能" in keywords or "深度学习" in keywords or "机器学习" in keywords
        )

    def test_filters_pure_symbols(self):
        from agents.memory_manager import _extract_keyword_cloud

        cloud = _extract_keyword_cloud(["### --- *** test"], top_k=5)
        keywords = [c["keyword"] for c in cloud]
        assert "###" not in keywords
        assert "---" not in keywords

    def test_empty_input(self):
        from agents.memory_manager import _extract_keyword_cloud

        cloud = _extract_keyword_cloud([], top_k=10)
        assert cloud == []

    def test_weights_are_normalized(self):
        from agents.memory_manager import _extract_keyword_cloud

        cloud = _extract_keyword_cloud(
            ["人工智能 人工智能 人工智能 数据 数据 算法"], top_k=5
        )
        weights = {c["keyword"]: c["weight"] for c in cloud}
        # "人工智能" should have higher weight than single-occurrence words
        assert weights.get("人工智能", 0) > weights.get("算法", 0)


# ═══════════════════════════════════════════════════════════════════════════
# Data collection
# ═══════════════════════════════════════════════════════════════════════════


class TestDataCollection:
    def test_collects_chat_click_search(self, memory_manager):
        memory_manager._track.get_recent.return_value = [
            {
                "id": 1,
                "event_type": "chat_message",
                "target_value": "今天有什么AI新闻",
                "metadata": '{"role": "user"}',
                "created_at": "2026-06-10T10:00:00",
            },
            {
                "id": 2,
                "event_type": "click_link",
                "target_value": "http://example.com/ai",
                "metadata": '{"title": "GPT-5 发布"}',
                "created_at": "2026-06-10T10:01:00",
            },
            {
                "id": 3,
                "event_type": "search",
                "target_value": "大模型",
                "metadata": "{}",
                "created_at": "2026-06-10T10:02:00",
            },
        ]

        chats, clicks, searches = memory_manager._collect_data()
        # User message repeated 3x for jieba emphasis
        assert len(chats) == 3
        assert "GPT-5 发布" in clicks
        assert "大模型" in searches
        assert memory_manager._last_event_id == 3

    def test_no_new_data(self, memory_manager):
        memory_manager._last_event_id = 100
        memory_manager._track.get_recent.return_value = []

        chats, clicks, searches = memory_manager._collect_data()
        assert chats == []
        assert clicks == []
        assert searches == []


# ═══════════════════════════════════════════════════════════════════════════
# Distillation cycle
# ═══════════════════════════════════════════════════════════════════════════


class TestDistillation:
    def test_cycle_with_llm(self, memory_manager):
        """LLM succeeds → profile from LLM output."""
        from agents.memory_manager import L2_PROFILE_FILE

        memory_manager._track.get_recent.return_value = [
            {
                "id": 1,
                "event_type": "chat_message",
                "target_value": "我对人工智能和深度学习很感兴趣",
                "metadata": '{"role": "user"}',
                "created_at": "2026-06-10T10:00:00",
            },
        ]
        memory_manager._call_llm_for_profile = AsyncMock(
            return_value={
                "active_interests": [
                    {"name": "人工智能", "weight": 0.8, "trend": "rising"}
                ],
                "emerging": [],
                "declining": [],
                "stable_interests": [
                    {"name": "人工智能", "strength": 0.7, "category": "科技"}
                ],
                "identity": "科技爱好者",
                "reading_habits": "深度阅读AI技术文章",
            }
        )

        import asyncio

        asyncio.run(memory_manager._distill())

        assert L2_PROFILE_FILE.exists()
        data = json.loads(L2_PROFILE_FILE.read_text(encoding="utf-8"))
        assert data["identity"] == "科技爱好者"
        assert data["stable_interests"][0]["name"] == "人工智能"

    def test_cycle_fallback_no_llm(self, memory_manager):
        """LLM fails → jieba cloud fallback still produces profile."""
        from agents.memory_manager import L2_PROFILE_FILE

        memory_manager._track.get_recent.return_value = [
            {
                "id": 1,
                "event_type": "chat_message",
                "target_value": "人工智能和机器学习的发展",
                "metadata": '{"role": "user"}',
                "created_at": "2026-06-10T10:00:00",
            },
        ]
        memory_manager._call_llm_for_profile = AsyncMock(return_value=None)

        import asyncio

        asyncio.run(memory_manager._distill())

        assert L2_PROFILE_FILE.exists()
        data = json.loads(L2_PROFILE_FILE.read_text(encoding="utf-8"))
        assert len(data["stable_interests"]) > 0

    def test_cycle_no_data(self, memory_manager):
        from agents.memory_manager import L2_PROFILE_FILE

        if L2_PROFILE_FILE.exists():
            L2_PROFILE_FILE.unlink()

        import asyncio

        asyncio.run(memory_manager._distill())

        # No data → no profile file created
        assert not L2_PROFILE_FILE.exists()


# ═══════════════════════════════════════════════════════════════════════════
# Profile fusion
# ═══════════════════════════════════════════════════════════════════════════


class TestFusion:
    def test_weighted_merge(self, memory_manager):
        old = {
            "stable_interests": [
                {"name": "AI", "strength": 0.9, "category": "科技"},
                {"name": "体育", "strength": 0.5, "category": "体育"},
            ]
        }
        new = {
            "stable_interests": [
                {"name": "AI", "strength": 0.7, "category": "科技"},
                {"name": "金融", "strength": 0.6, "category": "财经"},
            ]
        }
        fused = memory_manager._fuse(old, new)
        ai = next(i for i in fused["stable_interests"] if i["name"] == "AI")
        assert 0.8 < ai["strength"] < 0.9

    def test_drops_below_threshold(self, memory_manager):
        old = {
            "stable_interests": [{"name": "old", "strength": 0.16, "category": "其他"}]
        }
        new = {"stable_interests": []}
        fused = memory_manager._fuse(old, new)
        # 0.16 * 0.9 = 0.144 < 0.15 → dropped
        assert len(fused["stable_interests"]) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegration:
    def test_run_cycle(self, memory_manager):
        from agents.memory_manager import L2_PROFILE_FILE

        memory_manager._track.get_recent.return_value = [
            {
                "id": 1,
                "event_type": "chat_message",
                "target_value": "关注AI技术发展",
                "metadata": '{"role": "user"}',
                "created_at": "2026-06-10T10:00:00",
            },
        ]
        memory_manager._call_llm_for_profile = AsyncMock(
            return_value={
                "active_interests": [{"name": "AI", "weight": 0.8, "trend": "rising"}],
                "emerging": [],
                "declining": [],
                "stable_interests": [
                    {"name": "AI", "strength": 0.7, "category": "科技"}
                ],
                "identity": "技术爱好者",
                "reading_habits": "关注AI动态",
            }
        )

        import asyncio

        asyncio.run(memory_manager.run_cycle())

        assert L2_PROFILE_FILE.exists()
        assert memory_manager._last_run_at is not None
