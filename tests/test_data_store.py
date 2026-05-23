"""Tests for DataStore: snapshot CRUD, item queries, run logging."""

import os

import pytest
from data.store import DataStore


@pytest.fixture
def store(tmp_path):
    history = tmp_path / "history"
    db = tmp_path / "test.db"
    ds = DataStore(
        history_dir=str(history), db_path=str(db), csv_path=str(tmp_path / "out.csv")
    )
    return ds


class TestSnapshot:
    def test_save_and_load(self, store):
        items = [
            {"title": "News 1", "url": "/1", "tag": "科技"},
            {"title": "News 2", "url": "/2", "tag": "娱乐"},
        ]
        path = store.save_snapshot("test_site", "https://example.com", "abc123", items)
        assert os.path.exists(path)

        snap = store.get_last_snapshot("test_site")
        assert snap is not None
        assert snap["items_count"] == 2
        assert snap["content_hash"] == "abc123"
        assert len(snap["items"]) == 2

    def test_get_last_hash(self, store):
        store.save_snapshot("s1", "https://x.com", "hash_a", [])
        store.save_snapshot("s1", "https://x.com", "hash_b", [])
        assert store.get_last_hash("s1") == "hash_b"

    def test_get_last_hash_empty(self, store):
        assert store.get_last_hash("nonexistent") is None


class TestQuery:
    def test_query_by_tag(self, store):
        items = [
            {"title": "Tech News", "url": "/t", "tag": "科技"},
            {"title": "Sports News", "url": "/s", "tag": "体育"},
        ]
        store.save_snapshot("test", "https://x.com", "h1", items)

        results = store.query_items(site_name="test", tag="科技")
        assert len(results) == 1
        assert results[0]["title"] == "Tech News"

    def test_query_by_date_range(self, store):
        store.save_snapshot(
            "test",
            "https://x.com",
            "h1",
            [{"title": "Old", "url": "/o", "tag": "科技"}],
        )
        results = store.query_items(
            site_name="test", date_from="2020-01-01", date_to="2030-01-01"
        )
        assert len(results) == 1

    def test_query_empty(self, store):
        results = store.query_items(site_name="no_such_site")
        assert results == []


class TestRunLogs:
    def test_log_and_retrieve(self, store):
        store.log_run(
            "test", "success", items_found=10, changes_detected=3, total_tokens=500
        )
        store.log_run("test", "skipped_no_change", items_found=0, changes_detected=0)

        history = store.get_run_history("test", limit=10)
        assert len(history) == 2
        assert history[0]["status"] == "skipped_no_change"
        assert history[0]["total_tokens"] == 0
        assert history[1]["status"] == "success"
        assert history[1]["total_tokens"] == 500

    def test_log_error(self, store):
        store.log_run("test", "error", error_message="timeout", processing_time_ms=5000)
        history = store.get_run_history("test")
        assert history[0]["status"] == "error"

    def test_cost_summary_aggregates(self, store):
        store.log_run("site_a", "success", total_tokens=300, trace_id="t1")
        store.log_run("site_a", "success", total_tokens=500, trace_id="t2")
        store.log_run("site_b", "success", total_tokens=100, trace_id="t3")
        summary = store.get_cost_summary(days=365)
        assert len(summary) == 2
        site_a = next(s for s in summary if s["site_name"] == "site_a")
        assert site_a["total_tokens"] == 800
        assert site_a["runs"] == 2
        assert site_a["avg_tokens"] == 400.0
        site_b = next(s for s in summary if s["site_name"] == "site_b")
        assert site_b["total_tokens"] == 100

    def test_cost_summary_excludes_zero_tokens(self, store):
        store.log_run("site_x", "skipped_no_change", total_tokens=0)
        store.log_run("site_x", "error", total_tokens=0)
        summary = store.get_cost_summary(days=365)
        assert len(summary) == 0  # Zero-token runs excluded


class TestGetAllSnapshots:
    def test_ordered_by_id(self, store):
        store.save_snapshot(
            "s", "https://x.com", "h1", [{"title": "First", "url": "/1", "tag": "A"}]
        )
        store.save_snapshot(
            "s", "https://x.com", "h2", [{"title": "Second", "url": "/2", "tag": "B"}]
        )

        snaps = store.get_all_snapshots("s")
        assert len(snaps) == 2
        assert snaps[0]["items_count"] == 1
        assert snaps[1]["items_count"] == 1


class TestTagStats:
    def test_tag_stats(self, store):
        items = [
            {"title": "A", "url": "/a", "tag": "科技"},
            {"title": "B", "url": "/b", "tag": "科技"},
            {"title": "C", "url": "/c", "tag": "体育"},
        ]
        store.save_snapshot("test", "https://x.com", "h", items)
        stats = store.get_tag_stats(site_name="test")
        assert stats["科技"] == 2
        assert stats["体育"] == 1


class TestSourceType:
    def test_news_defaults(self, tmp_path):
        ds = DataStore(source_type="news")
        assert "monitor.db" in ds.db_path
        assert "history" in str(ds.history_dir)
        assert "news_items.csv" in str(ds.csv_path)

    def test_paper_defaults(self, tmp_path):
        ds = DataStore(source_type="paper")
        assert "papers.db" in ds.db_path
        assert "papers_history" in str(ds.history_dir)
        assert "papers.csv" in str(ds.csv_path)

    def test_explicit_overrides_source_type(self, tmp_path):
        db = tmp_path / "custom.db"
        ds = DataStore(source_type="news", db_path=str(db))
        assert ds.db_path == str(db)


class TestPruneSnapshots:
    def test_prune_keeps_recent(self, store):
        for i in range(5):
            store.save_snapshot(
                "s",
                "https://x.com",
                f"h{i}",
                [{"title": f"N{i}", "url": f"/{i}", "tag": "T"}],
            )
        store.prune_snapshots("s", keep_count=3)
        snaps = store.get_all_snapshots("s")
        assert len(snaps) == 3
        # Oldest removed, newest kept
        titles = [it["title"] for snap in snaps for it in snap["items"]]
        assert "N0" not in titles
        assert "N1" not in titles
        assert "N4" in titles

    def test_prune_noop_when_under_limit(self, store):
        store.save_snapshot(
            "s", "https://x.com", "h0", [{"title": "X", "url": "/x", "tag": "T"}]
        )
        store.prune_snapshots("s", keep_count=10)
        assert len(store.get_all_snapshots("s")) == 1

    def test_prune_zero_disabled(self, store):
        for i in range(5):
            store.save_snapshot(
                "s",
                "https://x.com",
                f"h{i}",
                [{"title": f"N{i}", "url": f"/{i}", "tag": "T"}],
            )
        store.prune_snapshots("s", keep_count=0)
        assert len(store.get_all_snapshots("s")) == 5


class TestMetadata:
    def test_update_and_get(self, store):
        store.update_metadata(
            "test",
            items_count=42,
            tag_dist={"科技": 20, "体育": 22},
            changes={"new": 5, "removed": 2, "modified": 1},
            update_summary="测试摘要",
        )
        meta = store.get_metadata("test")
        assert len(meta["count_history"]) == 1
        assert meta["count_history"][0][1] == 42
        assert meta["latest_tag_distribution"] == {"科技": 20, "体育": 22}
        assert meta["latest_changes"]["new"] == 5
        assert meta["latest_update_summary"] == "测试摘要"

    def test_empty_metadata(self, store):
        assert store.get_metadata("nonexistent") == {}

    def test_history_accumulates(self, store):
        store.update_metadata("s", 10, {"A": 10}, {"new": 1})
        store.update_metadata("s", 15, {"B": 15}, {"new": 2})
        meta = store.get_metadata("s")
        assert len(meta["count_history"]) == 2
        assert meta["count_history"][0][1] == 10
        assert meta["count_history"][1][1] == 15
        assert meta["latest_tag_distribution"] == {"B": 15}


class TestDedup:
    def test_is_similar_exact_match(self, store):
        assert store._is_similar("Hello World", "Hello World") is True

    def test_is_similar_high_similarity(self, store):
        assert (
            store._is_similar(
                "Breaking News: Something Important Happens Today",
                "Breaking News: Something Important Happens...",
            )
            is True
        )

    def test_is_similar_low_similarity(self, store):
        assert (
            store._is_similar("Weather Report: Sunny", "Financial Report: Stocks Rise")
            is False
        )

    def test_is_similar_empty_strings(self, store):
        assert store._is_similar("", "") is False
        assert store._is_similar("A", "") is False

    def test_deduplicate_items_removes_duplicates(self, store):
        # Save a snapshot first to build history
        store.save_snapshot(
            "dd",
            "https://x.com",
            "h0",
            [
                {
                    "title": "Breaking News: Something Important Happens Today",
                    "url": "/1",
                    "tag": "国际",
                }
            ],
        )
        # Second save: nearly duplicate title should be filtered
        items = [
            {
                "title": "Breaking News: Something Important Happens...",
                "url": "/1b",
                "tag": "国际",
            },
            {"title": "Completely Different News", "url": "/2", "tag": "科技"},
        ]
        result = store._deduplicate_items(items, "dd")
        assert len(result) == 1
        assert result[0]["title"] == "Completely Different News"

    def test_deduplicate_items_no_history(self, store):
        items = [{"title": "News A", "url": "/a"}, {"title": "News B", "url": "/b"}]
        result = store._deduplicate_items(items, "new_site")
        assert len(result) == 2

    def test_deduplicate_items_single_character_titles_not_merged(self, store):
        """Short titles like 'N0' and 'N1' should not be considered duplicates."""
        store.save_snapshot("sc", "https://x.com", "h0", [{"title": "N0", "url": "/0"}])
        items = [{"title": "N1", "url": "/1"}]
        result = store._deduplicate_items(items, "sc")
        assert len(result) == 1  # "N1" not similar enough to "N0"


class TestCircuitBreaker:
    def test_no_circuit_initially(self, store):
        assert store.is_circuit_open("cb_test") is False

    def test_circuit_closed_after_few_failures(self, store):
        for _ in range(3):
            store.increment_failure("cb_test")
        assert store.is_circuit_open("cb_test") is False

    def test_circuit_opens_after_5_failures(self, store):
        for _ in range(5):
            store.increment_failure("cb_test")
        assert store.is_circuit_open("cb_test") is True

    def test_reset_failure_closes_circuit(self, store):
        for _ in range(5):
            store.increment_failure("cb_test")
        assert store.is_circuit_open("cb_test") is True
        store.reset_failure("cb_test")
        assert store.is_circuit_open("cb_test") is False

    def test_reset_failure_before_threshold(self, store):
        for _ in range(3):
            store.increment_failure("cb_test")
        store.reset_failure("cb_test")
        # After reset, failures should start from 0
        for _ in range(4):
            store.increment_failure("cb_test")
        assert store.is_circuit_open("cb_test") is False  # Only 4 failures after reset
