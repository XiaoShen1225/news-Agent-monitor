"""MemoryManager tests — three-layer distillation pipeline."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_memory_dir():
    """Temporary directory with clean data/memory subdir."""
    with tempfile.TemporaryDirectory() as d:
        old_cwd = os.getcwd()
        os.chdir(d)
        Path("data/memory").mkdir(parents=True, exist_ok=True)
        Path("agents/prompts").mkdir(parents=True, exist_ok=True)
        # Write minial prompt templates for tests
        prompts_dir = Path("agents/prompts")
        prompts_dir.joinpath("l0_extract.txt").write_text(
            "提取用户兴趣信号。输出 JSON。", encoding="utf-8"
        )
        prompts_dir.joinpath("l1_aggregate.txt").write_text(
            "分析兴趣趋势。输出 JSON。", encoding="utf-8"
        )
        prompts_dir.joinpath("l2_profile.txt").write_text(
            "更新画像。输出 JSON。", encoding="utf-8"
        )
        try:
            yield Path(d)
        finally:
            os.chdir(old_cwd)


@pytest.fixture
def mock_track_store():
    """TrackStore mock with essential methods."""
    ts = MagicMock()
    ts.get_max_event_id.return_value = 100
    ts.get_chat_sessions.return_value = []
    ts.get_l0_events.return_value = []
    ts.get_l0_event_count_since.return_value = 0
    ts.get_recent.return_value = []
    ts.insert_l0_events.return_value = 0
    ts.expire_ttl_l0.return_value = None
    ts.purge_expired_l0.return_value = None
    return ts


@pytest.fixture
def memory_manager(mock_track_store, tmp_memory_dir):
    from agents.memory_manager import MemoryManager

    mm = MemoryManager(mock_track_store, {"model": "test-model"})
    return mm


# ═══════════════════════════════════════════════════════════════════════════
# L0 Extraction
# ═══════════════════════════════════════════════════════════════════════════


class TestL0Extraction:
    def test_skips_when_no_new_events(self, mock_track_store):
        from agents.memory_manager import MemoryManager

        mm = MemoryManager(mock_track_store)
        mm._last_analyzed_event_id = 100  # same as max
        # Should not call LLM
        mm._call_llm = AsyncMock()
        import asyncio

        asyncio.run(mm._extract_l0())
        mm._call_llm.assert_not_called()

    def test_skips_empty_sessions(self, memory_manager):
        memory_manager._track.get_max_event_id.return_value = 200
        memory_manager._call_llm = AsyncMock()
        import asyncio

        asyncio.run(memory_manager._extract_l0())
        memory_manager._call_llm.assert_not_called()

    def test_extracts_l0_from_sessions(self, memory_manager):
        memory_manager._track.get_max_event_id.return_value = 200
        memory_manager._track.get_chat_sessions.return_value = [
            {
                "session_id": "s1",
                "events": [
                    {
                        "id": 101,
                        "event_type": "chat_message",
                        "target_value": "我喜欢AI技术",
                        "metadata": '{"role": "user", "session_id": "s1"}',
                        "created_at": "2026-06-03T10:00:00",
                    },
                    {
                        "id": 102,
                        "event_type": "chat_message",
                        "target_value": "是的，AI技术是热门话题",
                        "metadata": '{"role": "assistant", "session_id": "s1"}',
                        "created_at": "2026-06-03T10:00:01",
                    },
                ],
            }
        ]
        memory_manager._call_llm = AsyncMock(
            return_value='{"topics": ["AI技术"], "entities": [], "summary": "用户对AI感兴趣", "is_explicit": false}'
        )
        memory_manager._track.insert_l0_events.return_value = 1

        import asyncio

        asyncio.run(memory_manager._extract_l0())

        memory_manager._call_llm.assert_called_once()
        memory_manager._track.insert_l0_events.assert_called_once()

    def test_detects_explicit_save(self, memory_manager):
        memory_manager._track.get_max_event_id.return_value = 200
        memory_manager._track.get_chat_sessions.return_value = [
            {
                "session_id": "s1",
                "events": [
                    {
                        "id": 101,
                        "event_type": "chat_message",
                        "target_value": "记住我喜欢量子计算",
                        "metadata": '{"role": "user", "session_id": "s1"}',
                        "created_at": "2026-06-03T10:00:00",
                    },
                ],
            }
        ]
        memory_manager._call_llm = AsyncMock(
            return_value='{"topics": ["量子计算"], "entities": [], "summary": "用户明确喜欢量子计算", "is_explicit": true}'
        )
        memory_manager._track.insert_l0_events.return_value = 1

        import asyncio

        asyncio.run(memory_manager._extract_l0())

        call_args = memory_manager._track.insert_l0_events.call_args[0][0]
        assert call_args[0]["is_explicit_save"] is True

    def test_handles_llm_failure_gracefully(self, memory_manager):
        memory_manager._track.get_max_event_id.return_value = 200
        memory_manager._track.get_chat_sessions.return_value = [
            {
                "session_id": "s1",
                "events": [
                    {
                        "id": 101,
                        "event_type": "chat_message",
                        "target_value": "测试",
                        "metadata": '{"role": "user", "session_id": "s1"}',
                        "created_at": "2026-06-03T10:00:00",
                    },
                ],
            }
        ]
        memory_manager._call_llm = AsyncMock(side_effect=Exception("API error"))

        import asyncio

        asyncio.run(memory_manager._extract_l0())

        # Should not crash, last id should update
        assert memory_manager._last_analyzed_event_id == 200


# ═══════════════════════════════════════════════════════════════════════════
# L1 Aggregation
# ═══════════════════════════════════════════════════════════════════════════


class TestL1Aggregation:
    def test_skips_when_insufficient_l0(self, memory_manager):
        memory_manager._track.get_l0_event_count_since.return_value = 5
        assert memory_manager._should_run_l1() is False

    def test_triggers_when_enough_l0(self, memory_manager):
        memory_manager._track.get_l0_event_count_since.return_value = 15
        memory_manager._last_l1_run_at = None  # first run
        assert memory_manager._should_run_l1() is True

    def test_skips_within_2h_cooldown(self, memory_manager):
        from datetime import datetime, timedelta

        memory_manager._track.get_l0_event_count_since.return_value = 15
        memory_manager._last_l1_run_at = (
            datetime.now() - timedelta(minutes=30)
        ).isoformat()
        assert memory_manager._should_run_l1() is False

    def test_l1_aggregation_with_mock_llm(self, memory_manager):
        from agents.memory_manager import L1_PATTERNS_FILE

        memory_manager._track.get_l0_events.return_value = [
            {
                "id": 1,
                "session_id": "s1",
                "topics": '["AI技术", "深度学习"]',
                "entities": "[]",
                "summary": "用户关注AI",
                "is_explicit_save": 0,
            }
            for _ in range(12)
        ]
        memory_manager._call_llm = AsyncMock(
            return_value=json.dumps(
                {
                    "period_summary": "用户关注AI技术",
                    "active_interests": [
                        {
                            "name": "AI技术",
                            "weight": 0.85,
                            "trend": "rising",
                            "evidence_count": 12,
                        }
                    ],
                    "emerging": [],
                    "declining": [],
                    "reading_pattern": "深度阅读科技内容",
                    "confidence": 0.8,
                }
            )
        )

        import asyncio

        asyncio.run(memory_manager._aggregate_l1())

        assert L1_PATTERNS_FILE.exists()
        data = json.loads(L1_PATTERNS_FILE.read_text(encoding="utf-8"))
        assert data["active_interests"][0]["name"] == "AI技术"


# ═══════════════════════════════════════════════════════════════════════════
# L2 Profile Update
# ═══════════════════════════════════════════════════════════════════════════


class TestL2ProfileUpdate:
    def test_skips_without_l1_data(self, memory_manager):
        from agents.memory_manager import L1_PATTERNS_FILE, L2_PROFILE_FILE

        # Clean up any leftover files
        if L1_PATTERNS_FILE.exists():
            L1_PATTERNS_FILE.unlink()
        if L2_PROFILE_FILE.exists():
            L2_PROFILE_FILE.unlink()
        assert memory_manager._should_run_l2() is False

    def test_skips_within_24h_cooldown(self, memory_manager):
        from datetime import datetime, timedelta
        from agents.memory_manager import L1_PATTERNS_FILE

        L1_PATTERNS_FILE.write_text(
            json.dumps(
                {
                    "active_interests": [
                        {
                            "name": "AI技术",
                            "weight": 0.85,
                            "trend": "rising",
                            "evidence_count": 12,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        memory_manager._last_l2_run_at = (
            datetime.now() - timedelta(hours=12)
        ).isoformat()
        assert memory_manager._should_run_l2() is False

    def test_l2_update_with_mock_llm(self, memory_manager):
        from datetime import datetime, timedelta
        from agents.memory_manager import L1_PATTERNS_FILE, L2_PROFILE_FILE

        L1_PATTERNS_FILE.write_text(
            json.dumps(
                {
                    "active_interests": [
                        {
                            "name": "AI技术",
                            "weight": 0.85,
                            "trend": "rising",
                            "evidence_count": 12,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        memory_manager._last_l2_run_at = (
            datetime.now() - timedelta(hours=48)
        ).isoformat()

        memory_manager._call_llm = AsyncMock(
            return_value=json.dumps(
                {
                    "identity": "科技从业者",
                    "stable_interests": [
                        {"name": "人工智能", "strength": 0.9, "category": "科技"}
                    ],
                    "reading_habits": "深度阅读",
                    "confidence": 0.75,
                    "changes_from_last": [],
                }
            )
        )

        import asyncio

        asyncio.run(memory_manager._update_l2())

        assert L2_PROFILE_FILE.exists()
        data = json.loads(L2_PROFILE_FILE.read_text(encoding="utf-8"))
        assert data["identity"] == "科技从业者"


# ═══════════════════════════════════════════════════════════════════════════
# Profile fusion
# ═══════════════════════════════════════════════════════════════════════════


class TestProfileFusion:
    def test_weighted_merge(self, memory_manager):
        old = {
            "identity": "学生",
            "stable_interests": [
                {"name": "AI", "strength": 0.9, "category": "科技"},
                {"name": "体育", "strength": 0.5, "category": "体育"},
            ],
        }
        new = {
            "identity": "科技从业者",
            "stable_interests": [
                {"name": "AI", "strength": 0.7, "category": "科技"},
                {"name": "金融", "strength": 0.6, "category": "财经"},
            ],
        }
        fused = memory_manager._fuse_profiles(old, new)

        # AI should be weighted: 0.9*0.7 + 0.7*0.3 = 0.84
        ai = next(i for i in fused["stable_interests"] if i["name"] == "AI")
        assert 0.8 < ai["strength"] < 0.9

        # Sports not in new — slight decay: 0.5 * 0.9 = 0.45
        sports = next(
            (i for i in fused["stable_interests"] if i["name"] == "体育"), None
        )
        assert sports is not None
        assert 0.4 < sports["strength"] < 0.5

    def test_drops_below_threshold(self, memory_manager):
        old = {
            "stable_interests": [
                {"name": "old_interest", "strength": 0.2, "category": "其他"}
            ]
        }
        new = {"stable_interests": []}
        fused = memory_manager._fuse_profiles(old, new)
        # 0.2 * 0.9 = 0.18 < 0.2 threshold → dropped
        assert len(fused["stable_interests"]) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestMemoryManagerIntegration:
    def test_run_cycle_no_data(self, memory_manager):
        from agents.memory_manager import L1_PATTERNS_FILE, L2_PROFILE_FILE

        # Clean up any leftover files from other tests
        if L1_PATTERNS_FILE.exists():
            L1_PATTERNS_FILE.unlink()
        if L2_PROFILE_FILE.exists():
            L2_PROFILE_FILE.unlink()

        import asyncio

        memory_manager._call_llm = AsyncMock()
        asyncio.run(memory_manager.run_cycle())
        # Should complete without error even with empty data
        memory_manager._call_llm.assert_not_called()

    def test_run_cycle_with_data(self, memory_manager):
        memory_manager._track.get_max_event_id.return_value = 200
        memory_manager._track.get_chat_sessions.return_value = [
            {
                "session_id": "s1",
                "events": [
                    {
                        "id": 101,
                        "event_type": "chat_message",
                        "target_value": "AI新闻",
                        "metadata": '{"role": "user", "session_id": "s1"}',
                        "created_at": "2026-06-03T10:00:00",
                    },
                ],
            }
        ]
        memory_manager._track.get_l0_event_count_since.return_value = 5
        memory_manager._call_llm = AsyncMock(
            return_value='{"topics": ["AI"], "entities": [], "summary": "...", "is_explicit": false}'
        )
        memory_manager._track.insert_l0_events.return_value = 1

        import asyncio

        asyncio.run(memory_manager.run_cycle())

        # L0 extraction should have been called
        memory_manager._call_llm.assert_called()
        assert memory_manager._last_analyzed_event_id == 200
