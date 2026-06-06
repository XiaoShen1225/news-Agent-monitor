"""Core fast tests — pure logic only, no LLM/network/model downloads."""

import pytest
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════════════════════════════
# BaseAgent: JSON parsing
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def base_agent():
    from agents.base_agent import BaseAgent

    return BaseAgent("TestAgent", {"llm": {"api_key": "test", "model": "glm-4-flash"}})


class TestJsonParsing:
    def test_valid_json_array(self, base_agent):
        assert base_agent.parse_json_response('[{"a": 1}, {"b": 2}]') == [
            {"a": 1},
            {"b": 2},
        ]

    def test_markdown_code_fence(self, base_agent):
        assert base_agent.parse_json_response('```json\n[{"x": "y"}]\n```') == [
            {"x": "y"}
        ]

    def test_trailing_comma(self, base_agent):
        assert base_agent.parse_json_response('[{"a": 1,}]') == [{"a": 1}]

    def test_surrounded_noise(self, base_agent):
        assert base_agent.parse_json_response('noise [{"k": "v"}] extra') == [
            {"k": "v"}
        ]

    def test_single_object_wrapped(self, base_agent):
        assert base_agent.parse_json_response('{"name": "test"}') == [{"name": "test"}]

    def test_truncated_array(self, base_agent):
        assert base_agent.parse_json_response('[{"a": 1}, {"b": 2}') == [
            {"a": 1},
            {"b": 2},
        ]

    def test_empty_raises(self, base_agent):
        with pytest.raises(ValueError):
            base_agent.parse_json_response("not json")

    def test_model_lazy_init(self, base_agent):
        assert base_agent._model is None


# ═══════════════════════════════════════════════════════════════════════════
# Sentiment analysis (zero-dependency, rule-based)
# ═══════════════════════════════════════════════════════════════════════════


class TestSentiment:
    def test_positive(self):
        from agents.sentiment_analyzer import classify

        assert classify("华为科技创新领先全球") == "positive"
        assert classify("中国经济强劲复苏增长") == "positive"

    def test_negative(self):
        from agents.sentiment_analyzer import classify

        assert classify("股市暴跌投资者恐慌") == "negative"
        assert classify("黑客攻击导致系统瘫痪") == "negative"

    def test_neutral(self):
        from agents.sentiment_analyzer import classify

        assert classify("今天天气多云转晴") == "neutral"
        assert classify("") == "neutral"

    def test_mixed(self):
        from agents.sentiment_analyzer import classify

        assert classify("突破危机实现增长") in ("positive", "negative", "neutral")


# ═══════════════════════════════════════════════════════════════════════════
# Fetcher: HTML cleaning + hash
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def fetcher():
    from agents.fetcher import FetcherAgent

    return FetcherAgent({"llm": {"api_key": "test"}})


class TestHtmlCleaning:
    def test_strips_script(self, fetcher):
        html = "<html><body><p>Hello</p><script>alert(1)</script></body></html>"
        assert "alert" not in fetcher._clean_html(html)
        assert "Hello" in fetcher._clean_html(html)

    def test_strips_style(self, fetcher):
        html = "<html><style>.a{color:red}</style><body>X</body></html>"
        assert "color" not in fetcher._clean_html(html)
        assert "X" in fetcher._clean_html(html)

    def test_normalizes_whitespace(self, fetcher):
        html = "<html><body>a   b\n\nc</body></html>"
        assert "   " not in fetcher._clean_html(html)


class TestHash:
    def test_deterministic(self, fetcher):
        assert fetcher._hash_text("hello") == fetcher._hash_text("hello")

    def test_different(self, fetcher):
        assert fetcher._hash_text("a") != fetcher._hash_text("b")

    def test_sha256_length(self, fetcher):
        assert len(fetcher._hash_text("x")) == 64


# ═══════════════════════════════════════════════════════════════════════════
# Clustering: cosine similarity + union-find
# ═══════════════════════════════════════════════════════════════════════════


class TestCosineSim:
    def test_identical(self):
        from agents.clustering import _cosine_sim

        assert _cosine_sim([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)

    def test_orthogonal(self):
        from agents.clustering import _cosine_sim

        assert _cosine_sim([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)

    def test_zero_vector(self):
        from agents.clustering import _cosine_sim

        assert _cosine_sim([0, 0], [1, 1]) == 0.0

    def test_opposite(self):
        from agents.clustering import _cosine_sim

        assert _cosine_sim([1, 1], [-1, -1]) == pytest.approx(-1.0)


class TestClusterItems:
    def test_empty(self):
        from agents.clustering import cluster_items

        assert cluster_items([], None) == []

    def test_single(self):
        from agents.clustering import cluster_items

        assert cluster_items([{"title": "x"}], None) == []

    def test_no_vector_store(self):
        from agents.clustering import cluster_items

        items = [{"title": "a"}, {"title": "b"}]
        assert cluster_items(items, None) == []


class FakeVectorStore:
    def __init__(self, embeddings_map):
        self._embeddings_map = embeddings_map

    def _ef(self, titles):
        return [self._embeddings_map.get(t) for t in titles]


class TestClusterWithEmbeddings:
    def test_similar_cluster(self):
        from agents.clustering import cluster_items

        vs = FakeVectorStore(
            {
                "华为发布新品": [0.9, 0.1],
                "华为推出新手机": [0.85, 0.15],
            }
        )
        items = [
            {"title": "华为发布新品", "site_name": "a", "tag": "科技"},
            {"title": "华为推出新手机", "site_name": "b", "tag": "科技"},
        ]
        clusters = cluster_items(items, vs, threshold=0.5)
        assert len(clusters) == 1
        assert clusters[0]["size"] == 2

    def test_dissimilar_no_cluster(self):
        from agents.clustering import cluster_items

        vs = FakeVectorStore(
            {
                "科技新闻": [1.0, 0.0],
                "体育新闻": [0.0, 1.0],
            }
        )
        items = [
            {"title": "科技新闻", "site_name": "a", "tag": "tech"},
            {"title": "体育新闻", "site_name": "b", "tag": "sports"},
        ]
        clusters = cluster_items(items, vs, threshold=0.5)
        assert len(clusters) == 0

    def test_min_cluster_size(self):
        from agents.clustering import cluster_items

        vs = FakeVectorStore(
            {
                "a": [1.0, 0.0],
                "b": [0.99, 0.01],
            }
        )
        items = [{"title": "a"}, {"title": "b"}]
        clusters = cluster_items(items, vs, threshold=0.5, min_cluster_size=3)
        assert len(clusters) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Parser: link validation
# ═══════════════════════════════════════════════════════════════════════════


class TestLinkValidation:
    def test_javascript_link(self):
        from agents.parser import ParserAgent

        p = ParserAgent({"llm": {"api_key": "test"}})
        assert not p._is_valid_link("click", "javascript:void(0)", set(), [])

    def test_hash_link(self):
        from agents.parser import ParserAgent

        p = ParserAgent({"llm": {"api_key": "test"}})
        assert not p._is_valid_link("more", "#section", set(), [])

    def test_valid_http(self):
        from agents.parser import ParserAgent

        p = ParserAgent({"llm": {"api_key": "test"}})
        assert p._is_valid_link(
            "2024年度重要新闻", "https://example.com/news/123", set(), []
        )


# ═══════════════════════════════════════════════════════════════════════════
# Coordinator: circuit breaker + error handling
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def coord_config():
    return {
        "llm": {"api_key": "test", "base_url": "https://test.api"},
        "storage": {"max_snapshots_per_site": 10},
    }


def _mock_store(**overrides):
    s = MagicMock()
    s.is_circuit_open.return_value = False
    s.get_last_hash.return_value = None
    s.log_run.return_value = None
    s.increment_failure.return_value = False
    s.reset_failure.return_value = None
    for k, v in overrides.items():
        setattr(s, k, MagicMock(return_value=v))
    return s


class TestCoordinatorCircuitBreaker:
    def test_skips_when_open(self, coord_config):
        from agents.coordinator import CoordinatorAgent

        store = _mock_store()
        store.is_circuit_open.return_value = True
        c = CoordinatorAgent(coord_config, data_store=store)
        result = c.run("https://x.com", "test")
        assert result["status"] == "circuit_open"

    def test_error_records_failure(self, coord_config):
        from agents.coordinator import CoordinatorAgent

        store = _mock_store()
        c = CoordinatorAgent(coord_config, data_store=store)
        with patch.object(c.fetcher, "run_async", side_effect=RuntimeError("boom")):
            result = c.run("https://x.com", "test")
        assert result["status"] == "error"
        store.increment_failure.assert_called_once()

    def test_empty_targets(self, coord_config):
        import asyncio
        from agents.coordinator import CoordinatorAgent

        coord_config["targets"] = []
        c = CoordinatorAgent(coord_config, data_store=MagicMock())
        result = asyncio.run(c.run_all_targets_async())
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# ChatAgent: input validation + context management
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def chat_agent():
    from agents.chat_agent import ChatAgent

    config = {
        "llm": {"api_key": "test", "model": "test"},
        "chat": {"max_history_tokens": 500, "min_exchanges": 1},
    }
    return ChatAgent(config)


class TestInputValidation:
    def test_empty_message(self, chat_agent):
        assert chat_agent._validate_input("") is not None
        assert chat_agent._validate_input("   ") is not None

    def test_too_long(self, chat_agent):
        assert chat_agent._validate_input("x" * 2001) is not None

    def test_blocked_operation(self, chat_agent):
        assert chat_agent._validate_input("删除数据库") is not None

    def test_valid_message(self, chat_agent):
        assert chat_agent._validate_input("今天有什么新闻？") is None


class TestContextManager:
    def test_count_tokens_chinese(self):
        from agents.context_manager import count_tokens

        n = count_tokens("你好世界")
        assert n >= 2

    def test_messages_tokens(self):
        from agents.context_manager import messages_tokens

        msgs = [{"role": "user", "content": "hi"}]
        t = messages_tokens(msgs)
        assert t > 0

    def test_get_exchanges_empty(self):
        from agents.context_manager import get_exchanges

        assert get_exchanges([]) == []

    def test_get_exchanges_single(self):
        from agents.context_manager import get_exchanges

        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        exchanges = get_exchanges(history)
        assert len(exchanges) == 1

    def test_get_exchanges_with_tools(self):
        from agents.context_manager import get_exchanges

        history = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "1",
                        "type": "function",
                        "function": {"name": "s", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "1", "content": "ok"},
            {"role": "assistant", "content": "found"},
        ]
        exchanges = get_exchanges(history)
        assert len(exchanges) == 1

    def test_trim_below_budget(self, chat_agent):
        from agents.context_manager import ContextManager

        ctx = ContextManager(max_history_tokens=99999)
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
        ]
        trimmed = ctx.trim_context(history)
        assert trimmed == 0
        assert len(history) == 2

    def test_trim_preserves_min_exchanges(self, chat_agent):
        from agents.context_manager import ContextManager

        ctx = ContextManager(max_history_tokens=1, min_exchanges=1)
        history = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        ctx.trim_context(history)
        # Should keep at least the last exchange (last 2 messages)
        assert len(history) == 2

    def test_cleanup_old_tool_results(self):
        from agents.context_manager import ContextManager

        ctx = ContextManager(max_tool_results=1)
        history = [
            {"role": "user", "content": "q"},
            {"role": "tool", "tool_call_id": "old", "content": "x" * 5000},
            {"role": "tool", "tool_call_id": "new", "content": "short"},
            {"role": "assistant", "content": "reply"},
        ]
        ctx.cleanup_old_tool_results(history)
        # Old tool result (before last assistant msg) should be truncated
        assert len(history[1]["content"]) < 5000


# ═══════════════════════════════════════════════════════════════════════════
# Provider factory: key resolution (pure logic, no LLM instantiation)
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveKey:
    def test_plain_value(self):
        from agents.provider_factory import _resolve_key

        assert _resolve_key("my-key") == "my-key"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_KEY", "from-env")
        from agents.provider_factory import _resolve_key

        assert _resolve_key("${TEST_KEY}") == "from-env"

    def test_missing_env(self):
        from agents.provider_factory import _resolve_key

        assert _resolve_key("${MISSING}") == ""

    def test_empty(self):
        from agents.provider_factory import _resolve_key

        assert _resolve_key("") == ""


# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# Web API: endpoint smoke tests (all mocked — no VectorStore init)
# ═══════════════════════════════════════════════════════════════════════════


async def _async_gen():
    yield "data: mock\n\n"


@pytest.fixture(autouse=True)
def _patch_web_runtime():
    import web.app as app_module

    app_config = {
        "targets": [{"url": "https://x.com", "name": "test", "use_browser": False}],
        "llm": {"api_key": "test"},
        "storage": {"max_snapshots_per_site": 10},
        "scheduler": {"default_interval_minutes": 60},
        "dashboard": {},
    }
    mc = MagicMock()
    mc.store = None
    mc.paper_store = None
    app_module.ctx.coordinator = mc
    app_module.ctx.scheduler = MagicMock()
    app_module.ctx.scheduler.running = True
    app_module.ctx.config = app_config

    mock_chat = MagicMock()
    mock_chat.chat.return_value = {"reply": "ok", "tool_calls": [], "context": {}}
    mock_chat.chat_stream.return_value = _async_gen()
    mock_chat._activate_session.return_value = "sid"
    mock_chat._history = []
    mock_chat.context_stats.return_value = {"history_tokens": 0, "exchanges": 0}
    mock_chat.clear_history.return_value = None
    mock_chat.list_sessions.return_value = []
    app_module.ctx.chat_agent = mock_chat

    yield
    app_module.ctx.chat_agent = None


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from web.app import app

    return TestClient(app)


class TestWebAPI:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_dashboard(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "News Agent Monitor" in r.text

    def test_targets(self, client):
        r = client.get("/api/targets")
        assert r.status_code == 200
        assert len(r.json()["targets"]) >= 1

    def test_stats(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        assert "sites" in r.json()

    def test_query(self, client):
        r = client.get("/api/query")
        assert r.status_code == 200

    def test_chart_data(self, client):
        r = client.get("/api/chart-data")
        assert r.status_code == 200

    def test_cost(self, client):
        r = client.get("/api/cost")
        assert r.status_code == 200

    def test_chat_empty_rejected(self, client):
        r = client.post("/api/chat", json={"message": ""})
        assert r.status_code == 400

    def test_chat_history(self, client):
        r = client.get("/api/chat/history")
        assert r.status_code == 200

    def test_chat_context(self, client):
        r = client.get("/api/chat/context")
        assert r.status_code == 200

    def test_chat_clear(self, client):
        r = client.delete("/api/chat")
        assert r.status_code == 200

    def test_chat_sessions(self, client):
        r = client.get("/api/chat/sessions")
        assert r.status_code == 200

    def test_alerts(self, client):
        r = client.get("/api/alerts")
        assert r.status_code == 200

    def test_stories(self, client):
        r = client.get("/api/stories")
        assert r.status_code == 200

    def test_trigger_run_no_coord(self, client):
        import web.app as app_module

        saved = app_module.ctx.coordinator
        app_module.ctx.coordinator = None
        try:
            r = client.post("/api/trigger-run?site=x&url=https://x.com")
            assert r.status_code == 503
        finally:
            app_module.ctx.coordinator = saved
