"""Tests for ChatAgent: context management, compression, tool result cleanup."""

import pytest
from agents.chat_agent import (
    ChatAgent,
    MAX_TOOL_RESULTS,
    _count_tokens,
    _messages_tokens,
)


class FakeStore:
    """Minimal DataStore stub for ChatAgent tests."""

    def query_items(self, site_name=None, tag=None, limit=10):
        return [
            {
                "title": "Test News",
                "tag": tag or "科技",
                "snapshot_time": "2026-05-23T10:00:00",
            }
        ]

    def get_metadata(self, site_name):
        return {
            "latest_tag_distribution": {"科技": 5, "娱乐": 3},
            "updated_at": "2026-05-23T10:00:00",
        }

    def get_run_history(self, site_name, limit=5):
        return [{"status": "success", "items_found": 10, "changes_detected": 3}]

    def get_circuit_status(self, site_name=None):
        if site_name:
            return {
                "site_name": site_name,
                "consecutive_failures": 0,
                "circuit_open": False,
                "circuit_breaker_until": None,
            }
        return [
            {
                "site_name": "baidu_news",
                "consecutive_failures": 0,
                "circuit_open": False,
                "circuit_breaker_until": None,
            },
        ]

    def get_events(self, limit=20):
        return []

    def get_entities(self, limit=50, entity_type=None):
        return []


@pytest.fixture
def agent():
    config = {"llm": {"api_key": "test", "model": "glm-4-flash"}}
    return ChatAgent(config, news_store=FakeStore())


class TestTokenEstimation:
    def test_chinese_text(self):
        tokens = _count_tokens("你好世界")
        assert tokens > 0

    def test_english_text(self):
        tokens = _count_tokens("Hello World")
        assert tokens > 0

    def test_messages_tokens(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        assert _messages_tokens(msgs) > 0


class TestGetExchanges:
    def test_empty_history(self, agent):
        assert agent._get_exchanges() == []

    def test_single_exchange(self, agent):
        agent._history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        exchanges = agent._get_exchanges()
        assert len(exchanges) == 1
        assert len(exchanges[0]) == 2

    def test_multiple_exchanges(self, agent):
        agent._history = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
        ]
        exchanges = agent._get_exchanges()
        assert len(exchanges) == 2

    def test_exchange_with_tool_calls(self, agent):
        agent._history = [
            {"role": "user", "content": "Query news"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "tc1",
                        "type": "function",
                        "function": {"name": "query_news", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "Result here"},
            {"role": "assistant", "content": "Here are the results"},
        ]
        exchanges = agent._get_exchanges()
        assert len(exchanges) == 1
        assert len(exchanges[0]) == 4  # user + tool_call + tool_result + reply


class TestTrimContext:
    def test_below_budget_no_trim(self, agent):
        agent._history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        trimmed = agent._trim_context()
        assert trimmed == 0
        assert len(agent._history) == 2

    def test_over_budget_trims_oldest(self, agent):
        # Make max very small to force trimming
        agent.max_history_tokens = 1
        agent._history = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
            {"role": "assistant", "content": "Second answer"},
        ]
        trimmed = agent._trim_context()
        assert trimmed >= 1
        # Newest exchange should be preserved
        assert any("Second" in m.get("content", "") for m in agent._history)

    def test_preserves_min_exchanges(self, agent):
        agent.max_history_tokens = 1
        agent._history = [
            {"role": "user", "content": "Only one exchange"},
            {"role": "assistant", "content": "Only answer"},
        ]
        trimmed = agent._trim_context()
        assert trimmed == 0  # Can't trim below MIN_EXCHANGES (1)
        assert len(agent._history) == 2


class TestCleanupOldToolResults:
    def test_recent_tool_results_preserved(self, agent):
        # Set up exactly MAX_TOOL_RESULTS tool messages
        agent._history = []
        for i in range(MAX_TOOL_RESULTS):
            agent._history.append({"role": "user", "content": f"Q{i}"})
            agent._history.append(
                {
                    "role": "tool",
                    "tool_call_id": f"tc{i}",
                    "content": f"Result {i}" * 20,
                }
            )
            agent._history.append({"role": "assistant", "content": f"A{i}"})
        agent._cleanup_old_tool_results()
        # All tool results should be preserved (within MAX_TOOL_RESULTS)
        for msg in agent._history:
            if msg.get("role") == "tool":
                assert not msg["content"].startswith("[已清除")

    def test_old_tool_results_truncated(self, agent):
        # Set up more than MAX_TOOL_RESULTS tool messages
        agent._history = []
        for i in range(MAX_TOOL_RESULTS + 3):
            agent._history.append({"role": "user", "content": f"Q{i}"})
            agent._history.append(
                {
                    "role": "tool",
                    "tool_call_id": f"tc{i}",
                    "content": f"Result {i}" * 20,
                }
            )
            agent._history.append({"role": "assistant", "content": f"A{i}"})
        agent._cleanup_old_tool_results()
        # Oldest 3 tool results should be truncated
        truncated = [
            m for m in agent._history if m.get("content", "").startswith("[已清除")
        ]
        assert len(truncated) == 3

    def test_short_tool_results_not_truncated(self, agent):
        agent._history = []
        for i in range(MAX_TOOL_RESULTS + 2):
            agent._history.append({"role": "user", "content": f"Q{i}"})
            agent._history.append(
                {"role": "tool", "tool_call_id": f"tc{i}", "content": "短结果"}
            )
            agent._history.append({"role": "assistant", "content": f"A{i}"})
        agent._cleanup_old_tool_results()
        # Short results (< 30 chars) should not trigger truncation
        truncated = [
            m for m in agent._history if "[已清除" in str(m.get("content", ""))
        ]
        assert len(truncated) == 0


class TestContextStats:
    def test_stats_zero(self, agent):
        stats = agent.context_stats()
        assert stats["history_tokens"] == 0
        assert stats["exchanges"] == 0
        assert stats["lifetime_trimmed"] == 0

    def test_stats_with_history(self, agent):
        agent._history = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
        ]
        agent._total_trimmed = 3
        agent._total_compressed = 2
        stats = agent.context_stats()
        assert stats["exchanges"] == 2
        assert stats["history_tokens"] > 0
        assert stats["lifetime_trimmed"] == 3
        assert stats["lifetime_compressed"] == 2
