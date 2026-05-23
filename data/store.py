"""Data persistence layer: JSON snapshots + SQLite metadata + CSV export."""

import json
import csv
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional


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
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS site_metadata (
                    site_name TEXT PRIMARY KEY,
                    count_history TEXT DEFAULT '[]',
                    latest_tag_distribution TEXT DEFAULT '{}',
                    latest_changes TEXT DEFAULT '{}',
                    latest_update_summary TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Index for fast queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_items_site_time
                ON news_items(site_name, snapshot_time)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_items_tag
                ON news_items(site_name, tag)
            """)
            conn.commit()

    def prune_snapshots(self, site_name: str, keep_count: int):
        """Keep only the most recent N snapshots for a site, delete older JSON + DB rows."""
        if keep_count <= 0:
            return
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, snapshot_path FROM snapshots WHERE site_name = ? ORDER BY id DESC",
                (site_name,),
            ).fetchall()
            if len(rows) <= keep_count:
                return
            to_delete = rows[keep_count:]  # oldest beyond keep_count
            for row in to_delete:
                snap_id, snap_path = row[0], row[1]
                # Delete JSON file
                try:
                    Path(snap_path).unlink(missing_ok=True)
                except Exception:
                    pass
                # Delete associated news_items and snapshot row
                conn.execute("DELETE FROM news_items WHERE snapshot_id = ?", (snap_id,))
                conn.execute("DELETE FROM snapshots WHERE id = ?", (snap_id,))
            conn.commit()

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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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

    def compute_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get_last_snapshot(self, site_name: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
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

    def get_last_hash(self, site_name: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT content_hash FROM snapshots WHERE site_name = ? ORDER BY id DESC LIMIT 1",
                (site_name,),
            ).fetchone()
        return row[0] if row else None

    def save_snapshot(
        self, site_name: str, url: str, content_hash: str, items: list
    ) -> str:
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

        with sqlite3.connect(self.db_path) as conn:
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

        # Append to CSV
        self._append_csv(site_name, now_iso, items)

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
        if date_from:
            conditions.append("snapshot_time >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("snapshot_time <= ?")
            params.append(date_to)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT title, url, tag, summary, snapshot_time, site_name FROM news_items {where} ORDER BY snapshot_time DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "title": r[0],
                "url": r[1],
                "tag": r[2],
                "summary": r[3],
                "snapshot_time": r[4],
                "site_name": r[5],
            }
            for r in rows
        ]

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

        with sqlite3.connect(self.db_path) as conn:
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
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO run_logs (site_name, status, items_found, changes_detected, "
                "extraction_confidence, processing_time_ms, error_message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    site_name,
                    status,
                    items_found,
                    changes_detected,
                    extraction_confidence,
                    processing_time_ms,
                    error_message,
                ),
            )
            conn.commit()

    def get_run_history(self, site_name: str, limit: int = 50) -> list:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT status, items_found, changes_detected, extraction_confidence, "
                "processing_time_ms, created_at FROM run_logs WHERE site_name = ? "
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
                "created_at": r[5],
            }
            for r in rows
        ]

    def get_all_snapshots(self, site_name: str) -> list:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT snapshot_path, created_at FROM snapshots WHERE site_name = ? ORDER BY id ASC",
                (site_name,),
            ).fetchall()

        snapshots = []
        for row in rows:
            path = Path(row[0])
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    snapshots.append(json.load(f))
        return snapshots
