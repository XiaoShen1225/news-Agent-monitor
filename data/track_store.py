"""Track user behavior events (clicks, searches, filters) for preference learning.

Single SQLite table.  Fire-and-forget writes from the frontend; periodic
batch reads from PreferenceEngine.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/track_events.db"


class TrackStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._path = Path(db_path)
        self._init_db()

    def _connect(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    target_value TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_user_events_type
                    ON user_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_user_events_created
                    ON user_events(created_at);

                CREATE TABLE IF NOT EXISTS l0_event_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    source_event_ids TEXT,
                    topics TEXT,
                    entities TEXT,
                    summary TEXT NOT NULL,
                    is_explicit_save INTEGER DEFAULT 0,
                    access_count INTEGER DEFAULT 0,
                    ttl_expires_at TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_l0_memory_status
                    ON l0_event_memory(status);
                CREATE INDEX IF NOT EXISTS idx_l0_memory_created
                    ON l0_event_memory(created_at);
                CREATE INDEX IF NOT EXISTS idx_l0_memory_session
                    ON l0_event_memory(session_id);
                """
            )

    # ── write ──────────────────────────────────────────────────────────

    def record(
        self, event_type: str, target_value: str = "", metadata: dict = None
    ) -> int:
        """Append an event. Returns row id."""
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO user_events (event_type, target_value, metadata) VALUES (?, ?, ?)",
                (event_type, target_value, meta_json),
            )
            return cur.lastrowid

    # ── read ───────────────────────────────────────────────────────────

    def get_recent(self, days: int = 30, event_types: list[str] = None) -> list[dict]:
        """Return events from the last N days, newest first."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            sql = (
                f"SELECT * FROM user_events WHERE created_at >= ? AND event_type IN ({placeholders}) "
                "ORDER BY created_at DESC"
            )
            params = [since] + event_types
        else:
            sql = "SELECT * FROM user_events WHERE created_at >= ? ORDER BY created_at DESC"
            params = [since]
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self, days: int = 30) -> dict:
        """Count events by type over the last N days."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_type, COUNT(*) AS cnt FROM user_events "
                "WHERE created_at >= ? GROUP BY event_type",
                (since,),
            ).fetchall()
        return {r["event_type"]: r["cnt"] for r in rows}

    # ── maintenance ────────────────────────────────────────────────────

    def total_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM user_events").fetchone()[0]

    def prune(self, days: int = 180):
        """Delete events older than N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM user_events WHERE created_at < ?", (cutoff,)
            )
            deleted = cur.rowcount
        if deleted:
            logger.info("TrackStore pruned %d events older than %d days", deleted, days)

    # ── chat session queries ───────────────────────────────────────────

    def get_chat_sessions(self, days: int = 1) -> list[dict]:
        """Return recent chat_message events grouped by session_id, for L0 extraction."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM user_events WHERE event_type = 'chat_message' "
                "AND created_at >= ? ORDER BY created_at ASC",
                (since,),
            ).fetchall()
        events = [dict(r) for r in rows]
        sessions: dict[str, list[dict]] = {}
        for e in events:
            meta = e.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            elif meta is None:
                meta = {}
            sid = meta.get("session_id", "__unknown__")
            sessions.setdefault(sid, []).append(e)
        return [{"session_id": sid, "events": evts} for sid, evts in sessions.items()]

    def get_events_since(
        self, since_id: int, event_types: list[str] = None
    ) -> list[dict]:
        """Get events with id > since_id. Optionally filter by event_type."""
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            sql = (
                f"SELECT * FROM user_events WHERE id > ? AND event_type IN ({placeholders}) "
                "ORDER BY id ASC"
            )
            params = [since_id] + event_types
        else:
            sql = "SELECT * FROM user_events WHERE id > ? ORDER BY id ASC"
            params = [since_id]
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_max_event_id(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(id) FROM user_events").fetchone()
            return row[0] or 0

    # ── L0 event memory ────────────────────────────────────────────────

    def get_l0_events(self, status: str = "active", limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM l0_event_memory WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_l0_event_count_since(self, since_timestamp: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM l0_event_memory WHERE created_at >= ?",
                (since_timestamp,),
            ).fetchone()
            return row[0] if row else 0

    def insert_l0_events(self, events: list[dict]) -> int:
        """Batch insert L0 events. Returns count of inserted rows."""
        with self._connect() as conn:
            cur = conn.executemany(
                "INSERT INTO l0_event_memory "
                "(session_id, source_event_ids, topics, entities, summary, "
                "is_explicit_save, ttl_expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.get("session_id", ""),
                        json.dumps(e.get("source_event_ids", []), ensure_ascii=False),
                        json.dumps(e.get("topics", []), ensure_ascii=False),
                        json.dumps(e.get("entities", []), ensure_ascii=False),
                        e.get("summary", ""),
                        int(e.get("is_explicit_save", False)),
                        (datetime.now() + timedelta(days=7)).isoformat(),
                    )
                    for e in events
                ],
            )
            return cur.rowcount

    def soft_delete_l0_event(self, event_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE l0_event_memory SET status = 'soft_deleted', "
                "updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), event_id),
            )

    def bump_l0_access(self, event_id: int):
        """Increment access_count and extend TTL."""
        new_ttl = (datetime.now() + timedelta(days=7)).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE l0_event_memory SET access_count = access_count + 1, "
                "ttl_expires_at = ?, updated_at = ? WHERE id = ?",
                (new_ttl, datetime.now().isoformat(), event_id),
            )

    def purge_expired_l0(self, cold_storage_days: int = 7):
        """Hard-delete soft_deleted L0 events older than N days."""
        cutoff = (datetime.now() - timedelta(days=cold_storage_days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM l0_event_memory WHERE status = 'soft_deleted' "
                "AND updated_at < ?",
                (cutoff,),
            )
            deleted = cur.rowcount
        if deleted:
            logger.info("Purged %d cold-storage L0 events", deleted)

    def expire_ttl_l0(self):
        """Soft-delete L0 events past their TTL."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE l0_event_memory SET status = 'soft_deleted', "
                "updated_at = ? WHERE status = 'active' AND ttl_expires_at < ?",
                (now, now),
            )
            if cur.rowcount:
                logger.info("Soft-deleted %d expired L0 events", cur.rowcount)
