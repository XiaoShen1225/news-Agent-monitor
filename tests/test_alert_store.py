"""Tests for AlertStore — keyword CRUD, cooldown, and matching."""

import tempfile


from data.alert_store import AlertStore


class TestKeywordCRUD:
    def test_add_new_keyword(self):
        store = _temp_store()
        r = store.add_keyword("华为")
        assert r["ok"] is True
        assert "华为" in r["msg"]
        kws = store.get_keywords()
        assert len(kws) == 1
        assert kws[0]["keyword"] == "华为"

    def test_add_duplicate_keyword(self):
        store = _temp_store()
        store.add_keyword("芯片")
        r = store.add_keyword("芯片")
        assert r["ok"] is True
        assert "已在" in r["msg"]
        assert len(store.get_keywords()) == 1

    def test_remove_existing_keyword(self):
        store = _temp_store()
        store.add_keyword("AI")
        r = store.remove_keyword("AI")
        assert r["ok"] is True
        assert len(store.get_keywords()) == 0

    def test_remove_nonexistent_keyword(self):
        store = _temp_store()
        r = store.remove_keyword("不存在")
        assert r["ok"] is False

    def test_list_keywords(self):
        store = _temp_store()
        store.add_keyword("GPT")
        store.add_keyword("DeepSeek")
        kws = store.get_keywords()
        assert len(kws) == 2
        names = [k["keyword"] for k in kws]
        assert "GPT" in names
        assert "DeepSeek" in names


class TestKeywordMatching:
    def test_match_title_contains_keyword(self):
        store = _temp_store()
        store.add_keyword("华为")
        items = [
            {"title": "华为发布新手机", "url": "https://example.com/1", "tag": "科技"},
            {"title": "今天天气不错", "url": "https://example.com/2", "tag": "其他"},
        ]
        matches = store.match_items(items)
        assert len(matches) == 1
        assert matches[0]["keyword"] == "华为"
        assert "发布新手机" in matches[0]["title"]

    def test_no_matches(self):
        store = _temp_store()
        store.add_keyword("苹果")
        items = [{"title": "小米发布新产品", "url": "", "tag": ""}]
        assert store.match_items(items) == []

    def test_no_keywords_configured(self):
        store = _temp_store()
        items = [{"title": "测试新闻", "url": "", "tag": ""}]
        assert store.match_items(items) == []

    def test_cooldown_prevents_duplicate(self):
        store = _temp_store()
        store.add_keyword("ESG")
        # First match should go through
        items = [{"title": "ESG投资成为热点", "url": "", "tag": ""}]
        matches1 = store.match_items(items)
        assert len(matches1) == 1
        # Second match within cooldown should be suppressed
        matches2 = store.match_items(items)
        assert matches2 == []


class TestAnomalyCooldown:
    def test_first_anomaly_allowed(self):
        store = _temp_store()
        assert store.should_alert_anomaly("baidu_news", "volume_spike") is True

    def test_anomaly_cooldown_blocks_duplicate(self):
        store = _temp_store()
        store.log_anomaly_alert("baidu_news", "volume_spike", "test")
        assert (
            store.should_alert_anomaly(
                "baidu_news", "volume_spike", cooldown_minutes=120
            )
            is False
        )

    def test_different_type_allowed(self):
        store = _temp_store()
        store.log_anomaly_alert("baidu_news", "volume_spike", "test")
        assert (
            store.should_alert_anomaly(
                "baidu_news", "volume_drop", cooldown_minutes=120
            )
            is True
        )

    def test_different_site_allowed(self):
        store = _temp_store()
        store.log_anomaly_alert("baidu_news", "volume_spike", "test")
        assert (
            store.should_alert_anomaly(
                "sina_news", "volume_spike", cooldown_minutes=120
            )
            is True
        )


class TestConfig:
    def test_load_config(self):
        store = _temp_store()
        config = {
            "alerts": {
                "anomaly": {"enabled": True, "zscore_threshold": 3.0},
                "keyword": {"cooldown_hours": 12},
                "sentiment": {"enabled": False},
            }
        }
        store.load_config(config)
        cfg = store.get_config()
        assert cfg["anomaly_zscore"] == 3.0
        assert cfg["keyword_cooldown_hours"] == 12
        assert cfg["sentiment_enabled"] is False

    def test_load_empty_config(self):
        store = _temp_store()
        store.load_config({})
        cfg = store.get_config()
        assert cfg["anomaly_enabled"] is True  # defaults


def _temp_store() -> AlertStore:
    """Create AlertStore backed by a temp file."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    store = AlertStore(path)
    return store
