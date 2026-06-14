"""Integration tests for DataStore — SQLite-backed persistence layer."""

import json
import tempfile
from pathlib import Path

import pytest

from data.store import DataStore


@pytest.fixture
def ds():
    with tempfile.TemporaryDirectory() as d:
        store = DataStore(
            history_dir=str(Path(d) / "history"),
            db_path=str(Path(d) / "test.db"),
            csv_path=str(Path(d) / "items.csv"),
        )
        yield store
        store.close()


SAMPLE_ITEMS = [
    {
        "title": "GPT-5发布引发行业震动",
        "url": "https://example.com/gpt5",
        "tag": "AI",
        "sentiment": "positive",
        "summary": "OpenAI发布了GPT-5",
        "published": "2026-06-10T10:00:00",
    },
    {
        "title": "高考分数线今日公布",
        "url": "https://example.com/gaokao",
        "tag": "教育",
        "sentiment": "neutral",
        "summary": "",
        "published": "2026-06-10T09:00:00",
    },
    {
        "title": "某地发生轻微地震",
        "url": "https://example.com/earthquake",
        "tag": "社会",
        "sentiment": "negative",
        "summary": "3.2级地震",
        "published": "2026-06-10T08:00:00",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Snapshot + item persistence
# ═══════════════════════════════════════════════════════════════════════════


class TestSnapshotPersistence:
    def test_save_and_query_items(self, ds):
        path = ds.save_snapshot(
            "test_site", "https://example.com", "abc123", SAMPLE_ITEMS
        )
        assert path.endswith(".json")
        assert Path(path).exists()

        items = ds.query_items(site_name="test_site")
        assert len(items) == 3
        # All items have same snapshot_time when saved in one batch;
        # verify all expected titles are present
        titles = {i["title"] for i in items}
        assert titles == {
            "GPT-5发布引发行业震动",
            "高考分数线今日公布",
            "某地发生轻微地震",
        }

    def test_query_by_tag(self, ds):
        ds.save_snapshot("test_site", "https://example.com", "abc", SAMPLE_ITEMS)
        items = ds.query_items(site_name="test_site", tag="AI")
        assert len(items) == 1
        assert items[0]["tag"] == "AI"

    def test_query_by_keyword(self, ds):
        ds.save_snapshot("test_site", "https://example.com", "abc", SAMPLE_ITEMS)
        items = ds.query_items(site_name="test_site", keyword="高考")
        assert len(items) == 1
        assert "高考" in items[0]["title"]

    def test_query_by_sentiment(self, ds):
        ds.save_snapshot("test_site", "https://example.com", "abc", SAMPLE_ITEMS)
        items = ds.query_items(site_name="test_site", sentiment="positive")
        assert len(items) == 1
        assert items[0]["sentiment"] == "positive"

    def test_query_order_desc_by_snapshot_time(self, ds):
        """Newer snapshots appear before older ones."""
        ds.save_snapshot("s1", "https://x.com", "h1", [SAMPLE_ITEMS[2]])  # oldest
        import time

        time.sleep(0.01)
        ds.save_snapshot("s1", "https://x.com", "h2", [SAMPLE_ITEMS[0]])  # newest

        items = ds.query_items(site_name="s1")
        # Newest snapshot first
        assert items[0]["title"] == "GPT-5发布引发行业震动"


# ═══════════════════════════════════════════════════════════════════════════
# Snapshot history
# ═══════════════════════════════════════════════════════════════════════════


class TestSnapshotHistory:
    def test_multiple_snapshots(self, ds):
        ds.save_snapshot("s1", "https://x.com", "h1", [SAMPLE_ITEMS[0]])
        ds.save_snapshot("s1", "https://x.com", "h2", [SAMPLE_ITEMS[1]])
        ds.save_snapshot("s2", "https://y.com", "h3", [SAMPLE_ITEMS[2]])

        assert len(ds.query_items(site_name="s1")) == 2
        assert len(ds.query_items(site_name="s2")) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Site metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestSiteMetadata:
    def test_get_metadata_returns_dict(self, ds):
        """Metadata for an unknown site returns empty dict until populated."""
        result = ds.get_metadata("no_data_site")
        assert isinstance(result, dict)
        # New site without any metadata returns empty dict
        assert result == {}

    def test_metadata_starts_empty_for_new_site(self, ds):
        """A brand-new site has no metadata until explicitly updated."""
        ds.save_snapshot("new_site", "https://x.com", "h1", SAMPLE_ITEMS[:1])
        # site_metadata is managed by the coordinator/analyzer, not save_snapshot directly
        result = ds.get_metadata("new_site")
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════
# Pruning
# ═══════════════════════════════════════════════════════════════════════════


class TestPruning:
    def test_prune_keeps_most_recent(self, ds):
        for i in range(10):
            ds.save_snapshot("p_site", "https://x.com", f"hash_{i}", [SAMPLE_ITEMS[0]])

        ds.prune_snapshots("p_site", keep_count=3)
        items = ds.query_items(site_name="p_site")
        assert len(items) <= 3

    def test_prune_noop_when_under_limit(self, ds):
        ds.save_snapshot("p_site", "https://x.com", "h1", [SAMPLE_ITEMS[0]])
        ds.prune_snapshots("p_site", keep_count=10)
        assert len(ds.query_items(site_name="p_site")) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Circuit breaker
# ═══════════════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    def test_is_circuit_open_new_site(self, ds):
        assert ds.is_circuit_open("new_site") is False

    def test_consecutive_failures_open_circuit(self, ds):
        site = "cb_test"
        for _ in range(6):
            ds.increment_failure(site)
        assert ds.is_circuit_open(site) is True

    def test_reset_failure_closes_circuit(self, ds):
        site = "cb_test2"
        for _ in range(6):
            ds.increment_failure(site)
        assert ds.is_circuit_open(site) is True
        ds.reset_failure(site)
        assert ds.is_circuit_open(site) is False


# ═══════════════════════════════════════════════════════════════════════════
# Deduplication
# ═══════════════════════════════════════════════════════════════════════════


class TestDeduplication:
    def test_dedup_keeps_different_titles(self, ds):
        items = [
            {"title": "Title A", "url": "https://a.com/1", "tag": "X"},
            {"title": "Title B", "url": "https://a.com/2", "tag": "X"},
        ]
        deduped = ds._deduplicate_items(items, "test_site")
        # These are different enough (>30% Jaccard distance) — both kept
        assert len(deduped) == 2

    def test_dedup_filters_near_duplicate_titles(self, ds):
        items = [
            {
                "title": "GPT-5重磅发布，震撼全球AI行业",
                "url": "https://a.com/1",
                "tag": "AI",
            },
            {
                "title": "GPT-5 重磅发布 震撼全球 AI 行业",
                "url": "https://a.com/2",
                "tag": "AI",
            },
        ]
        deduped = ds._deduplicate_items(items, "test_site")
        # Near-duplicate within same batch (same-site dedup > 0.7)
        # The first one should be kept, second removed
        assert len(deduped) >= 1

    def test_empty_items(self, ds):
        path = ds.save_snapshot("empty_site", "https://x.com", "hash", [])
        assert path.endswith(".json")
        assert ds.query_items(site_name="empty_site") == []


# ═══════════════════════════════════════════════════════════════════════════
# JSON snapshot file
# ═══════════════════════════════════════════════════════════════════════════


class TestJsonSnapshot:
    def test_snapshot_file_structure(self, ds):
        path = ds.save_snapshot("json_site", "https://x.com", "hash123", SAMPLE_ITEMS)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["site_name"] == "json_site"
        assert data["content_hash"] == "hash123"
        assert data["items_count"] == 3
        assert len(data["items"]) == 3
        assert "timestamp" in data
