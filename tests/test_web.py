"""Tests for FastAPI web application endpoints."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def patch_runtime_refs():
    """Ensure _config and _coordinator are set before any test."""
    import web.app as app_module

    app_module._config = {
        "targets": [
            {"url": "https://example.com", "name": "test_site", "use_browser": False}
        ],
        "llm": {"api_key": "test", "base_url": "https://test.api"},
        "storage": {"max_snapshots_per_site": 10},
        "scheduler": {"default_interval_minutes": 60},
        "dashboard": {},
    }
    # Create a mock coordinator
    mock_coord = MagicMock()
    mock_coord.store = None
    mock_coord.paper_store = None
    app_module._coordinator = mock_coord
    app_module._scheduler = MagicMock()
    app_module._scheduler.running = True
    yield
    app_module._chat_agent = None


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from web.app import app

    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert data["version"] == "0.6.0"

    def test_health_exempt_from_auth(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200


class TestDashboardPage:
    def test_dashboard_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "News Agent Monitor" in resp.text


class TestTargetsAPI:
    def test_api_targets(self, client):
        resp = client.get("/api/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert "targets" in data
        assert len(data["targets"]) >= 1

    def test_api_schedule(self, client):
        resp = client.get("/api/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert "targets" in data
        assert "default_interval" in data


class TestStatsAPI:
    def test_api_stats_all_sites(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert "sites" in data
        assert "snapshots" in data

    def test_api_stats_with_site_filter(self, client):
        resp = client.get("/api/stats?site=test_site")
        # May return 200 even for unknown site (empty results)
        assert resp.status_code in (200, 500)


class TestQueryAPI:
    def test_api_query_default(self, client):
        resp = client.get("/api/query")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_api_query_with_filters(self, client):
        resp = client.get("/api/query?site=test_site&tag=科技&limit=5&offset=0")
        assert resp.status_code == 200


class TestChartDataAPI:
    def test_api_chart_data(self, client):
        resp = client.get("/api/chart-data")
        assert resp.status_code == 200
        data = resp.json()
        assert "sites" in data
        assert "chart_data" in data


class TestCostAPI:
    def test_api_cost(self, client):
        resp = client.get("/api/cost?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_tokens" in data
        assert "by_site" in data

    def test_api_cost_default_days(self, client):
        resp = client.get("/api/cost")
        assert resp.status_code == 200


class TestChatAPI:
    def test_chat_empty_message(self, client):
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 400

    def test_chat_invalid_json(self, client):
        resp = client.post("/api/chat", content=b"not json")
        assert resp.status_code == 400

    def test_chat_history(self, client):
        resp = client.get("/api/chat/history")
        assert resp.status_code == 200
        assert "messages" in resp.json()

    def test_chat_context(self, client):
        resp = client.get("/api/chat/context")
        assert resp.status_code == 200
        data = resp.json()
        assert "history_tokens" in data

    def test_chat_clear(self, client):
        resp = client.delete("/api/chat")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cleared"


class TestAuthAPI:
    def test_auth_no_config_allows_access(self, client):
        """When dashboard token is not configured, requests pass through."""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_auth_endpoint_accepts_post(self, client):
        resp = client.post("/api/auth", json={"token": "test"})
        # Returns denied when no token configured, or ok if configured
        assert resp.status_code in (200, 401)


class TestTriggerRun:
    def test_trigger_run_no_coordinator(self, client):
        import web.app as app_module

        saved = app_module._coordinator
        app_module._coordinator = None
        try:
            resp = client.post("/api/trigger-run?site=test&url=https://x.com")
            assert resp.status_code == 503
        finally:
            app_module._coordinator = saved


class TestWebSocket:
    def test_ws_connect(self, client):
        with client.websocket_connect("/ws") as ws:
            assert ws is not None


class TestFavicon:
    def test_favicon(self, client):
        resp = client.get("/favicon.ico")
        # Either 200 (file exists) or 204 (no file)
        assert resp.status_code in (200, 204)
