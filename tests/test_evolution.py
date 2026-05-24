"""Tests for EvolutionOptimizer: schedule tuning logic."""

import pytest
from unittest.mock import MagicMock
from evolution.optimizer import EvolutionOptimizer


@pytest.fixture
def config():
    return {
        "targets": [
            {"url": "https://example.com", "name": "test_site", "interval_minutes": 60},
        ],
        "evolution": {
            "enabled": True,
            "min_runs_before_optimize": 3,
            "prompt_tuning": True,
            "schedule_tuning": True,
        },
    }


class TestScheduleTuning:
    def test_increase_frequency(self, config):
        memory = MagicMock()
        memory.get_stats.return_value = {
            "runs": 10,
            "change_frequency": 0.9,
        }
        memory.get_last_adjustment.return_value = None
        optimizer = EvolutionOptimizer(config, memory)
        result = optimizer._optimize_schedule("test_site", memory.get_stats())
        assert result is not None
        assert result["action"] == "increased_frequency"
        assert result["new_interval"] < result["old_interval"]

    def test_decrease_frequency(self, config):
        memory = MagicMock()
        memory.get_stats.return_value = {
            "runs": 10,
            "change_frequency": 0.05,
        }
        memory.get_last_adjustment.return_value = None
        optimizer = EvolutionOptimizer(config, memory)
        result = optimizer._optimize_schedule("test_site", memory.get_stats())
        assert result is not None
        assert result["action"] == "decreased_frequency"
        assert result["new_interval"] > result["old_interval"]

    def test_no_change_mid_range(self, config):
        memory = MagicMock()
        memory.get_stats.return_value = {
            "runs": 10,
            "change_frequency": 0.5,
        }
        memory.get_last_adjustment.return_value = None
        optimizer = EvolutionOptimizer(config, memory)
        result = optimizer._optimize_schedule("test_site", memory.get_stats())
        assert result is None

    def test_unknown_site(self, config):
        memory = MagicMock()
        memory.get_stats.return_value = {
            "runs": 10,
            "change_frequency": 0.9,
        }
        optimizer = EvolutionOptimizer(config, memory)
        result = optimizer._optimize_schedule("nonexistent_site", memory.get_stats())
        assert result is None


class TestPromptTuning:
    def test_high_confidence_skips(self, config):
        memory = MagicMock()
        stats = {"avg_confidence": 0.85, "runs": 10}
        optimizer = EvolutionOptimizer(config, memory)
        result = optimizer._optimize_prompt("test_site", stats)
        assert result is None


class TestRecordRun:
    def test_record_and_run(self, config):
        memory = MagicMock()
        memory.get_stats.return_value = {"runs": 2}
        optimizer = EvolutionOptimizer(config, memory)
        report = {"current_count": 10, "total_changes": 3, "has_changes": True}
        result = optimizer.record_run(
            "test_site", report, confidence=0.9, elapsed_ms=100
        )
        memory.add_record.assert_called_once()
        assert result["status"] == "insufficient_data"
