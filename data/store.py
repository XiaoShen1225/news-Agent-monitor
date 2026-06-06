"""Data persistence layer: JSON snapshots + SQLite metadata + CSV export."""

import json
import csv
import hashlib
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# Default path mapping per source type
_SOURCE_DEFAULTS = {
    "news": {
        "history_dir": "data/history",
        "db_path": "data/monitor.db",
        "csv_path": "outputs/data/news_items.csv",
    },
    "paper": {
        "history_dir": "data/papers_history",
        "db_path": "data/papers.db",
        "csv_path": "outputs/data/papers.csv",
    },
}


class DataStore:
    def __init__(
        self,
        history_dir: str = None,
        db_path: str = None,
        csv_path: str = None,
        source_type: str = None,
        bm25_index=None,
    ):
        # Resolve defaults: explicit args take priority, then source_type, then news defaults
        st = source_type or "news"
        defaults = _SOURCE_DEFAULTS.get(st, _SOURCE_DEFAULTS["news"])
        self.history_dir = Path(history_dir or defaults["history_dir"])
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or defaults["db_path"]
        self.csv_path = Path(csv_path or defaults["csv_path"])
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_type = st
        self._bm25 = bm25_index
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    @contextmanager
    def _get_conn(self):
        """Yield a cached SQLite connection (WAL mode, single-thread safe)."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield self._conn
        except Exception:
            self._conn.rollback()
            raise

    def close(self):
        """Close the cached connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    items_count INTEGER DEFAULT 0,
                    snapshot_path TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    site_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    tag TEXT DEFAULT '',
                    sentiment TEXT DEFAULT '',
                    snapshot_time TIMESTAMP NOT NULL,
                    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
                )
            """)
            # Add new columns for existing databases (check first)
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(news_items)").fetchall()
            }
            if "sentiment" not in cols:
                conn.execute(
                    "ALTER TABLE news_items ADD COLUMN sentiment TEXT DEFAULT ''"
                )
            if "summary" not in cols:
                conn.execute(
                    "ALTER TABLE news_items ADD COLUMN summary TEXT DEFAULT ''"
                )
            if "published" not in cols:
                conn.execute(
                    "ALTER TABLE news_items ADD COLUMN published TEXT DEFAULT ''"
                )
            if "image_url" not in cols:
                conn.execute(
                    "ALTER TABLE news_items ADD COLUMN image_url TEXT DEFAULT ''"
                )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    items_found INTEGER DEFAULT 0,
                    changes_detected INTEGER DEFAULT 0,
                    extraction_confidence REAL DEFAULT 0.0,
                    processing_time_ms REAL DEFAULT 0,
                    error_message TEXT,
                    trace_id TEXT DEFAULT '',
                    total_tokens INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migrations: add new columns to existing run_logs tables
            for col, col_def in [
                ("trace_id", "TEXT DEFAULT ''"),
                ("total_tokens", "INTEGER DEFAULT 0"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE run_logs ADD COLUMN {col} {col_def}")
                except Exception:
                    pass  # Column already exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS site_metadata (
                    site_name TEXT PRIMARY KEY,
                    count_history TEXT DEFAULT '[]',
                    latest_tag_distribution TEXT DEFAULT '{}',
                    latest_changes TEXT DEFAULT '{}',
                    latest_update_summary TEXT DEFAULT '',
                    consecutive_failures INTEGER DEFAULT 0,
                    circuit_breaker_until TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migration: add circuit breaker columns to existing site_metadata tables
            for col in ["consecutive_failures", "circuit_breaker_until"]:
                try:
                    conn.execute(
                        f"ALTER TABLE site_metadata ADD COLUMN {col} INTEGER DEFAULT 0"
                        if col == "consecutive_failures"
                        else f"ALTER TABLE site_metadata ADD COLUMN {col} TEXT DEFAULT ''"
                    )
                except Exception:
                    pass  # Column already exists
            # Index for fast queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_items_site_time
                ON news_items(site_name, snapshot_time)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_items_tag
                ON news_items(site_name, tag)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_name TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    interval_minutes INTEGER DEFAULT 60,
                    use_browser INTEGER DEFAULT 0,
                    extraction_strategy TEXT DEFAULT 'auto',
                    profile_json TEXT DEFAULT '{}',
                    is_article_source INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def prune_snapshots(self, site_name: str, keep_count: int):
        """Keep only the most recent N snapshots for a site, delete older JSON + DB rows."""
        if keep_count <= 0:
            return
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, snapshot_path FROM snapshots WHERE site_name = ? ORDER BY id DESC",
                (site_name,),
            ).fetchall()
            if len(rows) <= keep_count:
                return
            to_delete = rows[keep_count:]  # oldest beyond keep_count
            # Delete DB rows first (transactional), then JSON files (best-effort)
            for row in to_delete:
                snap_id = row[0]
                conn.execute("DELETE FROM news_items WHERE snapshot_id = ?", (snap_id,))
                conn.execute("DELETE FROM snapshots WHERE id = ?", (snap_id,))
            conn.commit()
            # Delete JSON files after DB commit — orphaned files are harmless
            for row in to_delete:
                try:
                    Path(row[1]).unlink(missing_ok=True)
                except Exception:
                    pass

    def update_metadata(
        self,
        site_name: str,
        items_count: int,
        tag_dist: dict,
        changes: dict,
        update_summary: str = "",
        timestamp: str = None,
    ):
        """Upsert per-site metadata for fast dashboard queries without full snapshot scan."""
        ts = timestamp or datetime.now().isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT count_history FROM site_metadata WHERE site_name = ?",
                (site_name,),
            ).fetchone()

            if row:
                history = json.loads(row[0] or "[]")
            else:
                history = []
            history.append([ts, items_count])
            # Keep history bounded (last 200 entries)
            if len(history) > 200:
                history = history[-200:]

            conn.execute(
                """INSERT INTO site_metadata (site_name, count_history, latest_tag_distribution,
                   latest_changes, latest_update_summary, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(site_name) DO UPDATE SET
                   count_history = excluded.count_history,
                   latest_tag_distribution = excluded.latest_tag_distribution,
                   latest_changes = excluded.latest_changes,
                   latest_update_summary = excluded.latest_update_summary,
                   updated_at = excluded.updated_at""",
                (
                    site_name,
                    json.dumps(history, ensure_ascii=False),
                    json.dumps(tag_dist, ensure_ascii=False),
                    json.dumps(changes, ensure_ascii=False),
                    update_summary or "",
                    ts,
                ),
            )
            conn.commit()

    def get_metadata(self, site_name: str) -> dict:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT count_history, latest_tag_distribution, latest_changes, "
                "latest_update_summary, updated_at FROM site_metadata WHERE site_name = ?",
                (site_name,),
            ).fetchone()
        if not row:
            return {}
        return {
            "count_history": json.loads(row[0] or "[]"),
            "latest_tag_distribution": json.loads(row[1] or "{}"),
            "latest_changes": json.loads(row[2] or "{}"),
            "latest_update_summary": row[3] or "",
            "updated_at": row[4] or "",
        }

    # ── Circuit breaker ──────────────────────────────────────────────

    def increment_failure(self, site_name: str) -> bool:
        """Increment consecutive_failures. Returns True if circuit is now OPEN."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO site_metadata (site_name, consecutive_failures)
                   VALUES (?, 1)
                   ON CONFLICT(site_name) DO UPDATE SET
                   consecutive_failures = consecutive_failures + 1,
                   updated_at = excluded.updated_at""",
                (site_name,),
            )
            row = conn.execute(
                "SELECT consecutive_failures FROM site_metadata WHERE site_name = ?",
                (site_name,),
            ).fetchone()
            failures = row[0] if row else 1
            if failures >= 5:
                until = (
                    datetime.now().replace(minute=0, second=0, microsecond=0)
                    + timedelta(hours=1)
                ).isoformat()
                conn.execute(
                    "UPDATE site_metadata SET circuit_breaker_until = ? WHERE site_name = ?",
                    (until, site_name),
                )
                conn.commit()
                return True
            conn.commit()
            return False

    def reset_failure(self, site_name: str):
        """Reset consecutive_failures to 0 and clear circuit breaker."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO site_metadata (site_name, consecutive_failures, circuit_breaker_until)
                   VALUES (?, 0, '')
                   ON CONFLICT(site_name) DO UPDATE SET
                   consecutive_failures = 0,
                   circuit_breaker_until = '',
                   updated_at = CURRENT_TIMESTAMP""",
                (site_name,),
            )
            conn.commit()

    def is_circuit_open(self, site_name: str) -> bool:
        """Return True if the circuit breaker is currently OPEN for this site."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT circuit_breaker_until FROM site_metadata WHERE site_name = ?",
                (site_name,),
            ).fetchone()
        if not row or not row[0]:
            return False
        return row[0] > datetime.now().isoformat()

    def get_circuit_status(self, site_name: str = None) -> dict | list[dict]:
        """Return circuit breaker status for one or all sites."""
        now = datetime.now().isoformat()
        if site_name:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT site_name, consecutive_failures, circuit_breaker_until "
                    "FROM site_metadata WHERE site_name = ?",
                    (site_name,),
                ).fetchone()
            if not row:
                return {
                    "site_name": site_name,
                    "consecutive_failures": 0,
                    "circuit_open": False,
                    "circuit_breaker_until": None,
                }
            cb_until = row[2]
            return {
                "site_name": row[0],
                "consecutive_failures": row[1],
                "circuit_open": bool(cb_until and cb_until > now),
                "circuit_breaker_until": cb_until,
            }
        # All sites
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT site_name, consecutive_failures, circuit_breaker_until FROM site_metadata"
            ).fetchall()
        results = []
        for row in rows:
            cb_until = row[2]
            results.append(
                {
                    "site_name": row[0],
                    "consecutive_failures": row[1],
                    "circuit_open": bool(cb_until and cb_until > now),
                    "circuit_breaker_until": cb_until,
                }
            )
        return results

    # ── User targets CRUD ────────────────────────────────────────────

    def add_user_target(
        self,
        site_name: str,
        url: str,
        interval_minutes: int = 60,
        use_browser: bool = False,
        extraction_strategy: str = "auto",
        profile_json: str = "{}",
        is_article_source: bool = False,
    ) -> dict:
        """Insert or replace a user-defined monitoring target."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO user_targets
                   (site_name, url, interval_minutes, use_browser,
                    extraction_strategy, profile_json, is_article_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(site_name) DO UPDATE SET
                   url=excluded.url,
                   interval_minutes=excluded.interval_minutes,
                   use_browser=excluded.use_browser,
                   extraction_strategy=excluded.extraction_strategy,
                   profile_json=excluded.profile_json,
                   is_article_source=excluded.is_article_source,
                   updated_at=CURRENT_TIMESTAMP""",
                (
                    site_name,
                    url,
                    interval_minutes,
                    1 if use_browser else 0,
                    extraction_strategy,
                    profile_json,
                    1 if is_article_source else 0,
                ),
            )
            conn.commit()
        return self.get_user_target(site_name) or {}

    def remove_user_target(self, site_name: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM user_targets WHERE site_name = ?", (site_name,)
            )
            conn.commit()
            return cur.rowcount > 0

    def get_user_target(self, site_name: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT site_name, url, interval_minutes, use_browser,"
                " extraction_strategy, profile_json, is_article_source, enabled,"
                " created_at, updated_at FROM user_targets WHERE site_name = ?",
                (site_name,),
            ).fetchone()
        if not row:
            return None
        return dict(
            zip(
                [
                    "name",
                    "url",
                    "interval_minutes",
                    "use_browser",
                    "strategy",
                    "profile_json",
                    "is_article_source",
                    "enabled",
                    "created_at",
                    "updated_at",
                ],
                row,
            )
        )

    def list_user_targets(self, enabled_only: bool = True) -> list[dict]:
        with self._get_conn() as conn:
            query = (
                "SELECT site_name, url, interval_minutes, use_browser,"
                " extraction_strategy, profile_json, is_article_source, enabled,"
                " created_at, updated_at FROM user_targets"
            )
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY created_at"
            rows = conn.execute(query).fetchall()
        keys = [
            "name",
            "url",
            "interval_minutes",
            "use_browser",
            "strategy",
            "profile_json",
            "is_article_source",
            "enabled",
            "created_at",
            "updated_at",
        ]
        return [dict(zip(keys, r)) for r in rows]

    def update_user_target(self, site_name: str, **fields) -> bool:
        allowed = {
            "interval_minutes",
            "use_browser",
            "extraction_strategy",
            "profile_json",
            "is_article_source",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._get_conn() as conn:
            cur = conn.execute(
                f"UPDATE user_targets SET {set_clause}, updated_at = CURRENT_TIMESTAMP"
                " WHERE site_name = ?",
                (*updates.values(), site_name),
            )
            conn.commit()
            return cur.rowcount > 0

    def toggle_user_target(self, site_name: str, enabled: bool) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE user_targets SET enabled = ?, updated_at = CURRENT_TIMESTAMP"
                " WHERE site_name = ?",
                (1 if enabled else 0, site_name),
            )
            conn.commit()
            return cur.rowcount > 0

    # ── Deduplication ────────────────────────────────────────────────

    @staticmethod
    def _is_similar(a: str, b: str, threshold: float = 0.7) -> bool:
        """Check if two title strings likely refer to the same underlying item."""
        from .utils import title_similar

        return title_similar(a, b, threshold)

    def _deduplicate_items(self, items: list, site_name: str) -> list:
        """Two-pass dedup: same-site (0.7) then cross-site (0.85)."""
        # Pass 1: same-site dedup
        items = self._dedup_against_existing(items, site_name, threshold=0.7)

        # Pass 2: cross-site dedup against recent items from all sites
        cross_titles = self._get_recent_cross_site_items(limit=200)
        if cross_titles:
            kept = []
            removed = 0
            for item in items:
                title = item.get("title", "")
                if any(
                    self._is_similar(title, ct, threshold=0.85) for ct in cross_titles
                ):
                    removed += 1
                else:
                    kept.append(item)
            if removed > 0:
                logger.info(
                    "Cross-site dedup: removed %d/%d items for %s",
                    removed,
                    len(items),
                    site_name,
                )
            items = kept

        return items

    def _dedup_against_existing(
        self, items: list, site_name: str, threshold: float = 0.7
    ) -> list:
        """Filter out items whose titles are near-duplicates of recent snapshots for the same site."""
        recent_items = self._get_recent_items(site_name, snapshots=3)
        if not recent_items:
            return items

        kept = []
        removed = 0
        for item in items:
            title = item.get("title", "")
            if any(
                self._is_similar(title, existing_title, threshold=threshold)
                for existing_title in recent_items
            ):
                removed += 1
            else:
                kept.append(item)

        if removed > 0:
            logger.info(
                "Dedup: removed %d/%d near-duplicate items for %s",
                removed,
                len(items),
                site_name,
            )
        return kept

    def _get_recent_cross_site_items(self, limit: int = 200) -> list:
        """Get distinct titles from the most recent items across all sites."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT title FROM news_items ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def _get_recent_items(self, site_name: str, snapshots: int = 3) -> list:
        """Get all item titles from the most recent N snapshots for a site."""
        titles = []
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT snapshot_path FROM snapshots WHERE site_name = ? "
                "ORDER BY id DESC LIMIT ?",
                (site_name, snapshots),
            ).fetchall()
        for (path_str,) in rows:
            path = Path(path_str)
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        snap = json.load(f)
                    for item in snap.get("items", []):
                        if item.get("title"):
                            titles.append(item["title"])
                except Exception:
                    pass
        return titles

    def compute_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get_last_snapshot(self, site_name: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT snapshot_path, content_hash FROM snapshots WHERE site_name = ? ORDER BY id DESC LIMIT 1",
                (site_name,),
            ).fetchone()
        if row:
            path = Path(row[0])
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        return None

    def get_last_hash(self, site_name: str) -> str | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT content_hash FROM snapshots WHERE site_name = ? ORDER BY id DESC LIMIT 1",
                (site_name,),
            ).fetchone()
        return row[0] if row else None

    def save_snapshot(
        self, site_name: str, url: str, content_hash: str, items: list
    ) -> str:
        # Deduplicate near-duplicate items before saving
        items = self._deduplicate_items(items, site_name)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{site_name}_{timestamp}.json"
        filepath = self.history_dir / filename
        now_iso = datetime.now().isoformat()

        snapshot = {
            "site_name": site_name,
            "url": url,
            "content_hash": content_hash,
            "timestamp": now_iso,
            "items_count": len(items),
            "items": items,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "INSERT INTO snapshots (site_name, url, content_hash, items_count, snapshot_path) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (site_name, url, content_hash, len(items), str(filepath)),
                )
                snapshot_id = cursor.lastrowid

                # Insert individual news items into SQLite
                for item in items:
                    conn.execute(
                        "INSERT INTO news_items (snapshot_id, site_name, title, url, tag, sentiment, summary, published, snapshot_time) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            snapshot_id,
                            site_name,
                            item.get("title", ""),
                            item.get("url", ""),
                            item.get("tag", ""),
                            item.get("sentiment", ""),
                            item.get("summary", ""),
                            item.get("published", ""),
                            now_iso,
                        ),
                    )
                conn.commit()
        except Exception:
            # SQLite write failed — clean up orphaned JSON file
            try:
                filepath.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        # Append to CSV
        self._append_csv(site_name, now_iso, items)

        # Sync to BM25 index
        if self._bm25 is not None:
            for item in items:
                self._bm25.add(
                    item.get("title", ""),
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "site_name": site_name,
                        "tag": item.get("tag", ""),
                        "sentiment": item.get("sentiment", ""),
                        "summary": item.get("summary", ""),
                        "snapshot_time": now_iso,
                        "published": item.get("published", ""),
                    },
                )

        return str(filepath)

    def _append_csv(self, site_name: str, timestamp: str, items: list):
        """Append items to the unified CSV file."""
        file_exists = self.csv_path.exists()
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(
                    ["site_name", "snapshot_time", "title", "url", "tag", "summary"]
                )
            for item in items:
                writer.writerow(
                    [
                        site_name,
                        timestamp,
                        item.get("title", ""),
                        item.get("url", ""),
                        item.get("tag", ""),
                        item.get("summary", ""),
                    ]
                )

    def query_items(
        self,
        site_name: str = None,
        tag: str = None,
        keyword: str = None,
        sentiment: str = None,
        date_from: str = None,
        date_to: str = None,
        limit: int = 500,
    ) -> list:
        """Query news items from SQLite with optional filters."""
        conditions = []
        params = []
        if site_name:
            conditions.append("site_name = ?")
            params.append(site_name)
        if tag:
            conditions.append("tag = ?")
            params.append(tag)
        if keyword:
            conditions.append("title LIKE ?")
            params.append(f"%{keyword}%")
        if sentiment:
            conditions.append("sentiment = ?")
            params.append(sentiment)
        if date_from:
            conditions.append("snapshot_time >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("snapshot_time <= ?")
            params.append(date_to)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT title, url, tag, sentiment, summary, snapshot_time, published, site_name FROM news_items {where} ORDER BY snapshot_time DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "title": r[0],
                "url": r[1],
                "tag": r[2],
                "sentiment": r[3] or "",
                "summary": r[4],
                "snapshot_time": r[5],
                "published": r[6] or r[5],
                "site_name": r[7],
            }
            for r in rows
        ]

    def update_item_summary(self, url: str, summary: str):
        """Cache an LLM-generated summary for a news item URL."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE news_items SET summary = ? WHERE url = ?",
                (summary, url),
            )
            conn.commit()

    def update_item_image(self, url: str, image_url: str):
        """Cache an image URL for a news item URL."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE news_items SET image_url = ? WHERE url = ?",
                (image_url, url),
            )
            conn.commit()

    def get_item_image(self, url: str) -> str | None:
        """Retrieve cached image URL, or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT image_url FROM news_items WHERE url = ? AND image_url != '' ORDER BY id DESC LIMIT 1",
                (url,),
            ).fetchone()
        return row[0] if row else None

    def get_item_summary(self, url: str) -> str | None:
        """Retrieve a cached summary for a URL, or None if not cached."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT summary FROM news_items WHERE url = ? AND summary != '' ORDER BY id DESC LIMIT 1",
                (url,),
            ).fetchone()
        return row[0] if row else None

    def get_tag_stats(self, site_name: str = None, date_from: str = None) -> dict:
        """Get tag distribution stats for a site and time range."""
        conditions = []
        params = []
        if site_name:
            conditions.append("site_name = ?")
            params.append(site_name)
        if date_from:
            conditions.append("snapshot_time >= ?")
            params.append(date_from)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT tag, COUNT(*) as cnt FROM news_items {where} GROUP BY tag ORDER BY cnt DESC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return {r[0]: r[1] for r in rows}

    def log_run(
        self,
        site_name: str,
        status: str,
        items_found: int = 0,
        changes_detected: int = 0,
        extraction_confidence: float = 0.0,
        processing_time_ms: float = 0,
        error_message: str = None,
        trace_id: str = "",
        total_tokens: int = 0,
    ):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO run_logs (site_name, status, items_found, changes_detected, "
                "extraction_confidence, processing_time_ms, error_message, trace_id, total_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    site_name,
                    status,
                    items_found,
                    changes_detected,
                    extraction_confidence,
                    processing_time_ms,
                    error_message,
                    trace_id,
                    total_tokens,
                ),
            )
            conn.commit()

    def get_run_history(self, site_name: str, limit: int = 50) -> list:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT status, items_found, changes_detected, extraction_confidence, "
                "processing_time_ms, total_tokens, created_at FROM run_logs WHERE site_name = ? "
                "ORDER BY id DESC LIMIT ?",
                (site_name, limit),
            ).fetchall()
        return [
            {
                "status": r[0],
                "items_found": r[1],
                "changes_detected": r[2],
                "extraction_confidence": r[3],
                "processing_time_ms": r[4],
                "total_tokens": r[5] or 0,
                "created_at": r[6],
            }
            for r in rows
        ]

    def get_cost_summary(self, days: int = 7) -> list:
        """Aggregate token usage by site over the last N days."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT site_name, SUM(total_tokens) as sum_tokens, COUNT(*) as runs, "
                "AVG(total_tokens) as avg_tokens "
                "FROM run_logs "
                "WHERE created_at > datetime('now', ?) AND total_tokens > 0 "
                "GROUP BY site_name "
                "ORDER BY sum_tokens DESC",
                (f"-{days} days",),
            ).fetchall()
        return [
            {
                "site_name": r[0],
                "total_tokens": r[1] or 0,
                "runs": r[2],
                "avg_tokens": round(r[3] or 0, 1),
            }
            for r in rows
        ]

    def get_latest_stats(self, site_name: str) -> dict:
        """Return aggregated stats for a site: total_runs, recent_runs, tag_distribution."""
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM run_logs WHERE site_name = ?",
                (site_name,),
            ).fetchone()[0]
            recent = conn.execute(
                "SELECT COUNT(*) FROM run_logs WHERE site_name = ? "
                "AND created_at > datetime('now', '-7 days')",
                (site_name,),
            ).fetchone()[0]
            meta = conn.execute(
                "SELECT latest_tag_distribution FROM site_metadata WHERE site_name = ?",
                (site_name,),
            ).fetchone()
        tag_dist = json.loads(meta[0]) if meta and meta[0] else {}
        return {
            "total_runs": total or 0,
            "recent_runs": recent or 0,
            "tag_distribution": tag_dist,
        }

    def get_snapshot_meta_list(self, site_name: str) -> list[dict]:
        """Return lightweight metadata for all snapshots — no items loaded."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT snapshot_path, created_at FROM snapshots WHERE site_name = ? ORDER BY id ASC",
                (site_name,),
            ).fetchall()

        results = []
        for row in rows:
            path = Path(row[0])
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append(
                        {
                            "items_count": data.get(
                                "items_count", len(data.get("items", []))
                            ),
                            "timestamp": data.get("timestamp", ""),
                        }
                    )
            except (json.JSONDecodeError, OSError):
                continue
        return results

    def rebuild_bm25_index(self):
        """Rebuild BM25 index from all items in the news_items table."""
        if self._bm25 is None:
            return
        items = self.query_items(limit=100000)
        if items:
            self._bm25.rebuild(items)
            logger.info(
                "[DataStore] BM25 index rebuilt: %d items from %s",
                len(items),
                self.db_path,
            )
