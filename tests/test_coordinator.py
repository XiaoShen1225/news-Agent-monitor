"""Tests for CoordinatorAgent: pipeline orchestration."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def config():
    return {
        "llm": {
            "api_key": "test",
            "base_url": "https://test.api",
            "model": "glm-4-flash",
        },
        "targets": [
            {"url": "https://example.com", "name": "test_site", "interval_minutes": 60},
        ],
        "storage": {"max_snapshots_per_site": 10},
    }


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get_last_hash.return_value = None
    store.is_circuit_open.return_value = False
    store.get_all_snapshots.return_value = []
    return store


class TestInit:
    def test_creates_sub_agents(self, config, mock_store):
        from agents.coordinator import CoordinatorAgent

        c = CoordinatorAgent(config, data_store=mock_store)
        assert c.fetcher is not None
        assert c.parser is not None
        assert c.analyzer is not None
        assert c.visualizer is not None
        assert c.store is mock_store

    def test_max_snapshots_from_config(self, config, mock_store):
        from agents.coordinator import CoordinatorAgent

        c = CoordinatorAgent(config, data_store=mock_store)
        assert c.max_snapshots == 10

    def test_max_snapshots_default_zero(self, config, mock_store):
        del config["storage"]["max_snapshots_per_site"]
        from agents.coordinator import CoordinatorAgent

        c = CoordinatorAgent(config, data_store=mock_store)
        assert c.max_snapshots == 0


class TestCircuitBreaker:
    def test_skips_when_circuit_open(self, config, mock_store):
        mock_store.is_circuit_open.return_value = True
        from agents.coordinator import CoordinatorAgent

        c = CoordinatorAgent(config, data_store=mock_store)
        result = c.run("https://example.com", "test_site")
        assert result["status"] == "circuit_open"

    @pytest.mark.asyncio
    async def test_async_skips_when_circuit_open(self, config, mock_store):
        mock_store.is_circuit_open.return_value = True
        from agents.coordinator import CoordinatorAgent

        c = CoordinatorAgent(config, data_store=mock_store)
        result = await c.run_async("https://example.com", "test_site")
        assert result["status"] == "circuit_open"


class TestRunAllTargets:
    @pytest.mark.asyncio
    async def test_empty_targets(self, config, mock_store):
        config["targets"] = []
        from agents.coordinator import CoordinatorAgent

        c = CoordinatorAgent(config, data_store=mock_store)
        result = await c.run_all_targets_async()
        assert result == []

    @pytest.mark.asyncio
    async def test_runs_all_targets_concurrently(self, config, mock_store):
        config["targets"] = [
            {"url": "https://a.com", "name": "site_a", "interval_minutes": 60},
            {"url": "https://b.com", "name": "site_b", "interval_minutes": 120},
        ]
        mock_store.is_circuit_open.return_value = True  # skip both
        from agents.coordinator import CoordinatorAgent

        c = CoordinatorAgent(config, data_store=mock_store)
        results = await c.run_all_targets_async()
        assert len(results) == 2
        assert all(r["status"] == "circuit_open" for r in results)


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_fetch_error_tracks_failure(self, config, mock_store):
        from agents.coordinator import CoordinatorAgent

        c = CoordinatorAgent(config, data_store=mock_store)
        with patch.object(c.fetcher, "run_async", side_effect=RuntimeError("boom")):
            result = await c.run_async("https://example.com", "test_site")
        assert result["status"] == "error"
        assert result["error"] == "boom"
        mock_store.increment_failure.assert_called_once_with("test_site")
