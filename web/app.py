"""FastAPI web dashboard for the news monitoring system."""

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from .app_context import ctx
from .middleware.logging import install as _install_logging_middleware
from data.track_store import TrackStore
from agents.site_profiles import is_article_site as _is_article_site

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DB_PATH = PROJECT_ROOT / "data" / "monitor.db"
PAPERS_DB_PATH = PROJECT_ROOT / "data" / "papers.db"
TEMPLATES_DIR = Path(__file__).parent / "templates"
VECTOR_DB_DIR = PROJECT_ROOT / "data" / "vector_db"

app = FastAPI(title="News Agent Monitor", version="0.6.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Rate limiter ────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please slow down."},
    )


# ── Security headers middleware ──────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' ws: wss:;",
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ── Startup: API key validation ──────────────────────────────────────


@app.on_event("startup")
async def _validate_api_keys():
    cfg = ctx.config or {}
    llm_cfg = cfg.get("llm", {})
    providers = llm_cfg.get("providers", {})
    for name, pc in providers.items():
        key = pc.get("api_key", "") if isinstance(pc, dict) else ""
        if not key or key == "sk-placeholder":
            logger.warning(
                "[Security] LLM provider '%s' has empty or placeholder API key — calls will fail",
                name,
            )
    dashboard_token = cfg.get("dashboard", {}).get("token", "")
    if not dashboard_token:
        logger.warning(
            "[Security] DASHBOARD_TOKEN is not set — web dashboard is unprotected"
        )


# ── Request-ID + structured logging ───────────────────────────────────
_install_logging_middleware(app, json_format=False)

# Mount static assets (CSS, JS)
STATIC_DIR = PROJECT_ROOT / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── WebSocket manager ──────────────────────────────────────────────


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            try:
                self.active.remove(ws)
            except ValueError:
                pass

    async def broadcast(self, data: dict):
        # Snapshot active list under lock to avoid race with connect/disconnect
        async with self._lock:
            if not self.active:
                logger.debug(
                    "[WS] broadcast skipped: 0 active clients (type=%s)",
                    data.get("type", "?"),
                )
                return
            # Copy for safe iteration outside the lock
            clients = list(self.active)

        logger.debug(
            "[WS] broadcasting type=%s to %d clients",
            data.get("type", "?"),
            len(clients),
        )
        disconnected = []
        for ws in clients:
            try:
                await ws.send_json(data)
            except Exception:
                logger.debug("[WS] client send failed, removing from active")
                disconnected.append(ws)
        # Remove dead connections under lock
        if disconnected:
            async with self._lock:
                for ws in disconnected:
                    try:
                        self.active.remove(ws)
                    except ValueError:
                        pass


ws_manager = ConnectionManager()


def _get_vector_store():
    if ctx.vector_store is None:
        try:
            from data.vector_store import VectorStore

            ctx.vector_store = VectorStore(str(VECTOR_DB_DIR))
        except Exception as e:
            logger.warning(
                "VectorStore init failed (model download/network): %s. "
                "Semantic search and deep analysis will be unavailable.",
                e,
            )
            ctx.vector_store = None
    return ctx.vector_store


def _get_hybrid_searcher():
    if ctx.hybrid_searcher is None:
        from data.hybrid_search import BM25Index, HybridSearcher
        from data.store import DataStore

        vs = _get_vector_store()
        bm25_index = BM25Index()
        store = DataStore(
            history_dir=str(PROJECT_ROOT / "data" / "history"),
            db_path=str(DB_PATH),
            bm25_index=bm25_index,
        )
        if bm25_index.doc_count == 0:
            store.rebuild_bm25_index()
        cfg = ctx.config.get("search", {}) if ctx.config else {}
        ctx.hybrid_searcher = HybridSearcher(bm25_index, vs, cfg)
    return ctx.hybrid_searcher


# ── helpers ────────────────────────────────────────────────────────


_db_conn = None
_papers_db_conn = None


def _get_db():
    """Return a cached SQLite connection for monitor.db (WAL mode, reused across requests)."""
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _db_conn.execute("PRAGMA journal_mode=WAL")
        _db_conn.row_factory = sqlite3.Row
    return _db_conn


def _get_papers_db():
    """Return a cached SQLite connection for papers.db (WAL mode, reused across requests)."""
    global _papers_db_conn
    if _papers_db_conn is None:
        _papers_db_conn = sqlite3.connect(str(PAPERS_DB_PATH), check_same_thread=False)
        _papers_db_conn.execute("PRAGMA journal_mode=WAL")
        _papers_db_conn.row_factory = sqlite3.Row
    return _papers_db_conn


def _get_sites() -> list:
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT DISTINCT site_name FROM snapshots ORDER BY site_name"
        ).fetchall()
        return [r["site_name"] for r in rows]
    except Exception:
        return []


def _get_data_store():
    """Get or create a cached DataStore instance."""
    if ctx.data_store is None:
        from data.store import DataStore

        ctx.data_store = DataStore(
            history_dir=str(PROJECT_ROOT / "data" / "history"),
            db_path=str(DB_PATH),
        )
    return ctx.data_store


def _get_watch_store():
    if ctx.watch_store is None:
        from data.watch_store import WatchStore

        ctx.watch_store = WatchStore()
    return ctx.watch_store


def _build_watch_summary() -> dict:
    """Build watch_summary payload for WebSocket push (connect + broadcast)."""
    store = _get_watch_store()
    stale = store.get_stale_watches()
    active_watches = store.list_watches(status="active", include_matches=False)
    return {
        "type": "watch_summary",
        "active_count": len(active_watches),
        "stale": [
            {
                "id": s["id"],
                "title": s["title"],
                "days_since_match": s.get("days_since_match", 0),
            }
            for s in stale
        ],
        "total_matches": sum(w.get("match_count", 0) for w in active_watches),
    }


def _diff_items(prev_items: list, curr_items: list) -> dict:
    """Count new/removed/modified by delegating to AnalyzerAgent._diff_items."""
    from agents.analyzer import AnalyzerAgent

    analyzer = AnalyzerAgent({"llm": {"api_key": "unused"}})
    new, removed, modified = analyzer._diff_items(prev_items, curr_items)
    return {"new": len(new), "removed": len(removed), "modified": len(modified)}


def _build_chart_data(site_name: str, store) -> dict:
    """Build ECharts-friendly data dict for a single site, preferring metadata for speed."""
    # Try metadata first (fast path — no JSON file scan)
    meta = store.get_metadata(site_name)
    if meta and meta.get("count_history"):
        history = meta["count_history"]
        counts = [h[1] for h in history]
        times = [h[0] for h in history]

        direction = "stable"
        recent_avg = 0
        older_avg = 0
        if len(counts) >= 2:
            recent_avg = sum(counts[-3:]) / min(3, len(counts[-3:]))
            older_avg = sum(counts[: max(1, len(counts) - 3)]) / max(1, len(counts) - 3)
            if recent_avg > older_avg * 1.1:
                direction = "up"
            elif recent_avg < older_avg * 0.9:
                direction = "down"

        tag_dist = meta.get("latest_tag_distribution", {})
        tag_list = [
            {"name": k, "value": v}
            for k, v in sorted(tag_dist.items(), key=lambda x: x[1], reverse=True)
        ]
        changes = meta.get("latest_changes", {"new": 0, "removed": 0, "modified": 0})
        update_summary = meta.get("latest_update_summary", "")

        return {
            "tag_distribution": tag_list,
            "trends": {
                "snapshot_counts": counts,
                "snapshot_times": times,
                "direction": direction,
                "recent_average": round(recent_avg, 1),
                "older_average": round(older_avg, 1),
            },
            "changes": changes,
            "update_summary": update_summary,
            "summary": {
                "site_name": site_name,
                "timestamp": times[-1] if times else "",
                "current_count": counts[-1] if counts else 0,
                "previous_count": counts[-2] if len(counts) >= 2 else 0,
                "total_changes": sum(changes.values()),
                "trend_direction": direction,
                "llm_summary": update_summary,
                "new_count": changes.get("new", 0),
                "removed_count": changes.get("removed", 0),
                "modified_count": changes.get("modified", 0),
            },
        }

    # Slow path: fallback to full snapshot scan for existing data
    snap = store.get_last_snapshot(site_name)
    if not snap:
        return None

    items = snap.get("items", [])

    tag_dist = {}
    for item in items:
        t = item.get("tag", "其他") or "其他"
        tag_dist[t] = tag_dist.get(t, 0) + 1
    tag_list = [
        {"name": k, "value": v}
        for k, v in sorted(tag_dist.items(), key=lambda x: x[1], reverse=True)
    ]

    all_snaps = store.get_snapshot_meta_list(site_name)
    counts = [s["items_count"] for s in all_snaps]
    times = [s["timestamp"] for s in all_snaps]

    direction = "stable"
    recent_avg = 0
    older_avg = 0
    if len(counts) >= 2:
        recent_avg = sum(counts[-3:]) / min(3, len(counts[-3:]))
        older_avg = sum(counts[: max(1, len(counts) - 3)]) / max(1, len(counts) - 3)
        if recent_avg > older_avg * 1.1:
            direction = "up"
        elif recent_avg < older_avg * 0.9:
            direction = "down"

    changes = {"new": 0, "removed": 0, "modified": 0}
    if len(all_snaps) >= 2:
        prev_items = all_snaps[-2].get("items", [])
        changes = _diff_items(prev_items, items)

    update_summary = snap.get("update_summary", "") or ""

    return {
        "tag_distribution": tag_list,
        "trends": {
            "snapshot_counts": counts,
            "snapshot_times": times,
            "direction": direction,
            "recent_average": round(recent_avg, 1),
            "older_average": round(older_avg, 1),
        },
        "changes": changes,
        "sentiment_distribution": [],
        "update_summary": update_summary,
        "summary": {
            "site_name": site_name,
            "timestamp": snap.get("timestamp", ""),
            "current_count": len(items),
            "previous_count": all_snaps[-2].get("items_count", 0)
            if len(all_snaps) >= 2
            else 0,
            "total_changes": changes["new"] + changes["removed"] + changes["modified"],
            "trend_direction": direction,
            "llm_summary": update_summary,
            "new_count": changes["new"],
            "removed_count": changes["removed"],
            "modified_count": changes["modified"],
        },
    }


# ── REST API ───────────────────────────────────────────────────────


@app.get("/api/targets")
async def api_targets():
    """Return all monitoring targets (built-in + user)."""
    tm = _get_target_manager()
    all_t = tm.all_targets()
    builtin_count = sum(1 for t in all_t if t.get("source") == "builtin")
    user_count = sum(1 for t in all_t if t.get("source") == "user")
    return {
        "targets": [
            {
                "name": t.get("name", ""),
                "url": t.get("url", ""),
                "use_browser": bool(t.get("use_browser", False)),
                "interval_minutes": t.get("interval_minutes", 60),
                "strategy": t.get("strategy", ""),
                "is_article": bool(t.get("is_article_source", False)),
                "source": t.get("source", "builtin"),
                "enabled": bool(t.get("enabled", True)),
            }
            for t in all_t
        ],
        "builtin_count": builtin_count,
        "user_count": user_count,
    }


# ── TargetManager lazy init + scheduler helpers ────────────────────


def _get_target_manager():
    if ctx.target_manager is None:
        from .target_manager import TargetManager

        ctx.target_manager = TargetManager(ctx.config or {}, _get_data_store())
    return ctx.target_manager


def _add_scheduler_job(target: dict):
    """Add a monitoring job for a single target to the running scheduler."""
    if not ctx.scheduler or not ctx.scheduler.running:
        return
    name = target.get("name") or target.get("site_name", "")
    job_id = f"monitor_{name}"
    try:
        ctx.scheduler.remove_job(job_id)
    except Exception:
        pass
    tm = _get_target_manager()
    profile = tm.get_profile(name)
    ctx.scheduler.add_job(
        ctx.coordinator.run_async,
        "interval",
        minutes=target.get("interval_minutes", 60),
        kwargs={
            "url": target["url"],
            "site_name": name,
            "use_browser": target.get("use_browser", False),
            "profile": profile,
        },
        id=job_id,
        name=f"Monitor {name}",
        replace_existing=True,
    )
    logger.info("Scheduled dynamic target '%s'", name)


def _remove_scheduler_job(site_name: str):
    if not ctx.scheduler or not ctx.scheduler.running:
        return
    try:
        ctx.scheduler.remove_job(f"monitor_{site_name}")
        logger.info("Removed scheduler job for '%s'", site_name)
    except Exception:
        pass


# ── Target CRUD endpoints ──────────────────────────────────────────

TARGET_URL_IMPORT = """\
import httpx
import asyncio
import json
import re"""


@app.post("/api/targets/validate")
async def api_targets_validate(request: Request):
    """Pre-flight URL check: reachability + strategy detection."""
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url:
        return JSONResponse({"error": "url is required"}, status_code=400)
    from agents.site_profiles import auto_detect_strategy

    result = await auto_detect_strategy(url)
    return result


@app.post("/api/targets")
async def api_targets_add(request: Request):
    """Add a new monitoring target."""
    body = await request.json()
    url = (body.get("url") or "").strip()
    site_name = (body.get("site_name") or "").strip()
    if not url or not site_name:
        return JSONResponse({"error": "url and site_name required"}, status_code=400)
    tm = _get_target_manager()
    if tm.is_builtin(site_name):
        return JSONResponse(
            {"error": f"'{site_name}' is a built-in target"},
            status_code=409,
        )
    for t in tm.all_targets():
        if t["name"] == site_name and t.get("source") == "user":
            return JSONResponse(
                {"error": f"'{site_name}' already exists"},
                status_code=409,
            )
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.head(url)
            if resp.status_code >= 500:
                return JSONResponse(
                    {"error": f"URL returned {resp.status_code}"},
                    status_code=400,
                )
    except Exception as e:
        return JSONResponse(
            {"error": f"URL unreachable: {str(e)[:200]}"},
            status_code=400,
        )

    interval = body.get("interval_minutes", 60)
    use_browser = body.get("use_browser", False)
    strategy = body.get("strategy", "auto")
    is_article_source = body.get("is_article_source", False)
    profile = body.get("profile", {})

    target = tm.add_target(
        site_name=site_name,
        url=url,
        interval_minutes=interval,
        use_browser=use_browser,
        extraction_strategy=strategy,
        is_article_source=is_article_source,
        profile=profile,
    )

    _add_scheduler_job(target)

    if ctx.coordinator:

        async def _initial_fetch():
            try:
                profile = tm.get_profile(site_name)
                await ctx.coordinator.run_async(
                    url,
                    site_name,
                    use_browser=use_browser,
                    profile=profile,
                )
            except Exception as e:
                logger.error("Initial fetch for '%s' failed: %s", site_name, e)

        asyncio.create_task(_initial_fetch())

    return {"status": "ok", "target": target}


@app.delete("/api/targets/{site_name}")
async def api_targets_delete(site_name: str, cleanup: bool = Query(False)):
    """Remove a user target. Rejects built-in targets."""
    tm = _get_target_manager()
    if tm.is_builtin(site_name):
        return JSONResponse(
            {"error": "Cannot remove built-in target", "allowed": False},
            status_code=403,
        )
    _remove_scheduler_job(site_name)
    ok = tm.remove_target(site_name)
    if not ok:
        return JSONResponse({"error": "Target not found"}, status_code=404)
    if cleanup:
        store = _get_data_store()
        try:
            for table in ["news_items", "snapshots", "run_logs", "site_metadata"]:
                store._get_conn().execute(
                    f"DELETE FROM {table} WHERE site_name = ?", (site_name,)
                )
                store._get_conn().commit()
        except Exception:
            pass
    return {"status": "ok"}


@app.put("/api/targets/{site_name}")
async def api_targets_update(site_name: str, request: Request):
    """Update a user target's config."""
    tm = _get_target_manager()
    if tm.is_builtin(site_name):
        target = next((t for t in tm.all_targets() if t["name"] == site_name), None)
        if target and target.get("source") != "user":
            return JSONResponse(
                {"error": "Cannot modify built-in target config"},
                status_code=403,
            )
    body = await request.json()
    fields = {}
    for k in (
        "interval_minutes",
        "use_browser",
        "extraction_strategy",
        "profile_json",
        "is_article_source",
    ):
        if k in body:
            fields[k] = body[k]
    ok = tm.update_target(site_name, **fields)
    if not ok:
        return JSONResponse({"error": "Target not found"}, status_code=404)
    # Reschedule if interval changed
    if "interval_minutes" in fields:
        target = tm._store.get_user_target(site_name) or {}
        target.setdefault("url", "")
        target.setdefault("use_browser", False)
        target["name"] = site_name
        target["site_name"] = site_name
        target["interval_minutes"] = fields["interval_minutes"]
        _add_scheduler_job(target)
    return {"status": "ok"}


@app.post("/api/targets/{site_name}/toggle")
async def api_targets_toggle(site_name: str, request: Request):
    """Enable or disable a monitoring target."""
    body = await request.json()
    enabled = bool(body.get("enabled", True))
    tm = _get_target_manager()
    if tm.is_builtin(site_name):
        # Allow toggling built-in targets too (disables scheduler job)
        pass
    ok = tm.toggle_target(site_name, enabled)
    if not ok:
        return JSONResponse({"error": "Target not found"}, status_code=404)
    if enabled:
        target = tm._store.get_user_target(site_name) or {
            "name": site_name,
            "url": next(
                (t["url"] for t in tm.all_targets() if t["name"] == site_name),
                "",
            ),
            "use_browser": False,
            "interval_minutes": 60,
        }
        target["site_name"] = site_name
        _add_scheduler_job(target)
    else:
        _remove_scheduler_job(site_name)
    return {"status": "ok", "enabled": enabled}


@app.get("/api/papers")
async def api_papers(
    site: str | None = Query(None),
    keyword: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Query papers/articles from article-type sources (uses separate papers.db)."""
    cache_key = f"{site or ''}|{keyword or ''}|{limit}|{offset}"
    cached = _papers_cache.get(cache_key)
    if cached is not None:
        return cached

    conn = _get_papers_db()
    try:
        article_sources = list(_get_target_manager().get_paper_source_names())
        if site:
            source_list = [site] if site in article_sources else article_sources
        else:
            source_list = article_sources

        placeholders = ",".join("?" for _ in source_list)
        base_where = f"site_name IN ({placeholders})"
        params = list(source_list)

        if keyword:
            base_where += " AND title LIKE ?"
            params.append(f"%{keyword}%")

        count_query = f"SELECT COUNT(*) FROM news_items WHERE {base_where}"
        total_row = conn.execute(count_query, params).fetchone()
        total = total_row[0] if total_row else 0

        query = (
            f"SELECT title, url, tag, summary, snapshot_time, site_name FROM news_items "
            f"WHERE {base_where} "
            f"ORDER BY snapshot_time DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        items = [dict(r) for r in rows]

        sources = {}
        for s in source_list:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM news_items WHERE site_name = ?", (s,)
            ).fetchone()[0]
            sources[s] = cnt

        result = {
            "items": items,
            "count": len(items),
            "total": total,
            "offset": offset,
            "limit": limit,
            "sources": sources,
        }
        _papers_cache.set(cache_key, result)
        return result
    finally:
        pass


@app.get("/api/schedule")
async def api_schedule_status():
    """Return current scheduler status and config."""
    cached = _schedule_cache.get("schedule")
    if cached is not None:
        return cached

    targets = ctx.config.get("targets", []) if ctx.config else []
    scheduler_cfg = ctx.config.get("scheduler", {}) if ctx.config else {}
    result = {
        "targets": [
            {
                "name": t.get("name", ""),
                "url": t.get("url", ""),
                "interval_minutes": t.get(
                    "interval_minutes",
                    scheduler_cfg.get("default_interval_minutes", 60),
                ),
                "is_article": _is_article_site(
                    t.get("name", ""), _get_target_manager()
                ),
            }
            for t in targets
        ],
        "default_interval": scheduler_cfg.get("default_interval_minutes", 60),
    }
    _schedule_cache.set("schedule", result)
    return result


class TTLCache:
    """Simple in-memory TTL cache with max-size eviction."""

    def __init__(self, maxsize: int = 128, ttl: float = 5.0):
        self._data: dict = {}
        self._maxsize = maxsize
        self._ttl = ttl

    def get(self, key):
        entry = self._data.get(key)
        if entry and (time.monotonic() - entry["ts"]) < self._ttl:
            return entry["data"]
        return None

    def set(self, key, data):
        if len(self._data) >= self._maxsize:
            # Evict oldest 25% of entries
            n = max(1, self._maxsize // 4)
            sorted_keys = sorted(self._data.keys(), key=lambda k: self._data[k]["ts"])
            for k in sorted_keys[:n]:
                del self._data[k]
        self._data[key] = {"ts": time.monotonic(), "data": data}

    def clear(self):
        self._data.clear()


_stats_cache = TTLCache(maxsize=64, ttl=2.0)


@app.get("/api/stats")
async def api_stats(
    site: str | None = Query(None),
):
    # Short-lived cache to absorb duplicate calls (monitor drawer fires 3 at once)
    cache_key = site or "__all__"
    cached = _stats_cache.get(cache_key)
    if cached is not None:
        return cached

    conn = _get_db()
    try:
        # Run logs (with error_message for health diagnostics)
        if site:
            rows = conn.execute(
                "SELECT status, items_found, changes_detected, extraction_confidence, "
                "processing_time_ms, error_message, created_at FROM run_logs "
                "WHERE site_name = ? ORDER BY id DESC LIMIT 20",
                (site,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT site_name, status, items_found, changes_detected, "
                "processing_time_ms, error_message, created_at FROM run_logs "
                "ORDER BY id DESC LIMIT 50"
            ).fetchall()

        runs = [dict(r) for r in rows]

        # Latest snapshot per site — single query instead of N+1
        sites = _get_sites()
        snapshots = {}
        snap_rows = conn.execute(
            "SELECT s.site_name, s.items_count, s.created_at "
            "FROM snapshots s "
            "INNER JOIN (SELECT site_name, MAX(id) AS max_id FROM snapshots GROUP BY site_name) latest "
            "ON s.site_name = latest.site_name AND s.id = latest.max_id"
        ).fetchall()
        snapshots = {
            r["site_name"]: {
                "items_count": r["items_count"],
                "created_at": r["created_at"],
            }
            for r in snap_rows
        }

        # Per-site health: consecutive_failures + circuit_breaker_until
        site_health = {}
        meta_rows = conn.execute(
            "SELECT site_name, consecutive_failures, circuit_breaker_until "
            "FROM site_metadata"
        ).fetchall()
        meta_map = {r[0]: (r[1] or 0, r[2] or "") for r in meta_rows}

        for s in sites:
            last_run = None
            for r in runs:
                if r.get("site_name", site) == s:
                    last_run = r
                    break
            failures, circuit_until = meta_map.get(s, (0, ""))
            circuit_open = bool(
                circuit_until and circuit_until > datetime.now().isoformat()
            )
            snap = snapshots.get(s, {})
            site_health[s] = {
                "last_run_status": last_run["status"] if last_run else "never",
                "last_run_time": last_run["created_at"] if last_run else None,
                "last_run_items": last_run.get("items_found", 0) if last_run else 0,
                "error_message": last_run.get("error_message", "") if last_run else "",
                "consecutive_failures": failures,
                "circuit_open": circuit_open,
                "last_snapshot_time": snap.get("created_at"),
                "last_snapshot_items": snap.get("items_count", 0),
            }

        data = {
            "runs": runs,
            "snapshots": snapshots,
            "sites": sites,
            "site_health": site_health,
        }
        _stats_cache.set(cache_key, data)
        return data
    finally:
        pass


@app.get("/api/query")
async def api_query(
    site: str | None = Query(None),
    tag: str | None = Query(None),
    keyword: str | None = Query(None),
    sentiment: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # Cache key from all query parameters
    cache_key = f"{site or ''}|{tag or ''}|{keyword or ''}|{sentiment or ''}|{date_from or ''}|{date_to or ''}|{limit}|{offset}"
    cached = _query_cache.get(cache_key)
    if cached is not None:
        return cached

    conditions = []
    params = []
    if site:
        conditions.append("site_name = ?")
        params.append(site)
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

    # Get total count for pagination
    count_query = f"SELECT COUNT(*) FROM news_items {where}"
    conn = _get_db()
    try:
        total_row = conn.execute(count_query, params).fetchone()
        total = total_row[0] if total_row else 0

        query = (
            f"SELECT title, url, tag, sentiment, summary, snapshot_time, site_name FROM news_items "
            f"{where} ORDER BY snapshot_time DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        items = [dict(r) for r in rows]

        # Tag distribution (across all items matching site filter, not just this page)
        tag_params = []
        tag_where = ""
        if site:
            tag_where = "WHERE site_name = ?"
            tag_params.append(site)
        tag_rows = conn.execute(
            f"SELECT tag, COUNT(*) as cnt FROM news_items {tag_where} GROUP BY tag ORDER BY cnt DESC",
            tag_params,
        ).fetchall()
        tags = {r["tag"]: r["cnt"] for r in tag_rows}

        result = {
            "items": items,
            "count": len(items),
            "total": total,
            "offset": offset,
            "limit": limit,
            "tags": tags,
        }
        _query_cache.set(cache_key, result)
        return result
    finally:
        pass


@app.get("/api/search")
async def api_search(
    q: str = Query(..., min_length=1, description="Search query"),
    site: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """Semantic search over news items using vector embeddings."""
    vs = _get_vector_store()
    results = vs.search(q, site_name=site, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/search/hybrid")
async def api_search_hybrid(
    q: str = Query(..., min_length=1, description="Search query"),
    site: str | None = Query(None),
    tag: str | None = Query(None),
    days: int | None = Query(None, ge=0, le=30),
    limit: int = Query(15, ge=1, le=50),
):
    """Hybrid search: BM25 keyword + vector semantic + RRF fusion."""
    hs = _get_hybrid_searcher()
    date_from = None
    if days is not None:
        date_from = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    results = hs.search(
        query=q,
        site_name=site,
        tag=tag,
        date_from=date_from,
        limit=limit,
    )
    return {
        "query": q,
        "method": "hybrid",
        "results": results,
        "count": len(results),
    }


_chart_cache = TTLCache(maxsize=32, ttl=5.0)
_papers_cache = TTLCache(maxsize=64, ttl=10.0)
_schedule_cache = TTLCache(maxsize=4, ttl=60.0)
_query_cache = TTLCache(maxsize=128, ttl=5.0)


@app.get("/api/chart-data")
async def api_chart_data(
    site: str | None = Query(None),
):
    """Return structured chart data for ECharts rendering."""
    cache_key = site or "__all__"
    cached = _chart_cache.get(cache_key)
    if cached is not None:
        return cached

    store = _get_data_store()
    sites = _get_sites()
    if not sites:
        return {"sites": [], "chart_data": {}}

    target_sites = [site] if site and site in sites else sites
    chart_data = {}
    for s in target_sites:
        data = _build_chart_data(s, store)
        if data:
            chart_data[s] = data

    result = {"sites": sites, "chart_data": chart_data}
    _chart_cache.set(cache_key, result)
    return result


@app.get("/api/summarize")
async def api_summarize(
    url: str = Query(..., min_length=1, description="Article URL to summarize"),
    title: str = Query("", description="Article title for context"),
):
    """Fetch article content and return an LLM-generated summary."""
    from agents.base_agent import BaseAgent

    if not ctx.config:
        return JSONResponse({"error": "LLM not configured"}, status_code=503)

    agent = None
    http_client = None
    try:
        # Step 1: fetch article HTML
        import httpx

        http_client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            trust_env=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        resp = await http_client.get(url)
        if resp.status_code == 403:
            html = "<html><body><p>该网站拒绝自动访问（403 Forbidden），请手动打开链接查看。</p></body></html>"
        else:
            resp.raise_for_status()
            html = resp.text

        if not html:
            return {"url": url, "title": title, "summary": "无法获取文章内容。"}

        # Step 2: extract text from HTML
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = text[:3000]

        # Step 3: LLM summarize
        agent = BaseAgent("Summarizer", ctx.config)
        summary = await agent.call_llm_async(
            system_prompt="你是一个新闻摘要助手。用 2-3 句中文简洁准确地概括文章核心内容，不超过 120 字。",
            user_prompt=f"标题：{title}\n\n文章内容：\n{text}\n\n请用中文摘要这篇文章的要点。",
            max_tokens=250,
            temperature=0.2,
            fallback=None,
        )

        return {
            "url": url,
            "title": title,
            "summary": summary or "摘要生成失败，请稍后重试。",
        }

    except Exception as e:
        logger.warning("[API] Summarize failed for %s: %s", url, e)
        return {"url": url, "title": title, "summary": f"摘要生成失败: {str(e)[:100]}"}
    finally:
        if agent is not None:
            await agent.aclose()
        if http_client is not None:
            await http_client.aclose()


# ── Dashboard auth ──────────────────────────────────────────────────


def _resolve_dashboard_token() -> str | None:
    """Resolve dashboard token from config, supporting ${ENV_VAR} syntax."""
    raw = ""
    if ctx.config:
        raw = ctx.config.get("dashboard", {}).get("token", "")
    if not raw:
        return None
    if raw.startswith("${") and raw.endswith("}"):
        raw = os.environ.get(raw[2:-1], "")
    return raw.strip() or None


def _get_effective_token() -> str | None:
    if ctx.dashboard_token is None:
        ctx.dashboard_token = _resolve_dashboard_token()
    return ctx.dashboard_token


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Simple cookie-based auth. Skips if DASHBOARD_TOKEN is not configured."""
    if request.url.path in ("/api/health", "/api/auth"):
        return await call_next(request)

    token = _get_effective_token()
    if token is None:
        return await call_next(request)

    cookie_val = request.cookies.get("dashboard_token", "")
    if cookie_val == token:
        return await call_next(request)

    return JSONResponse({"error": "unauthorized"}, status_code=401)


@app.post("/api/auth")
async def api_auth(request: Request):
    """Validate token and set cookie."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    token_input = (body.get("token") or "").strip()
    expected = _get_effective_token()
    if not expected or token_input != expected:
        return JSONResponse({"status": "denied"}, status_code=401)

    resp = JSONResponse({"status": "ok"})
    resp.set_cookie(
        key="dashboard_token",
        value=token_input,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )
    return resp


# ── Action endpoints (CLI features in dashboard) ────────────────────

# Coordinator reference — set by _cmd_serve_async on startup
ctx.coordinator = None
ctx.config = None
_app_start = datetime.now()
ctx.last_run_time = None
ctx.scheduler = None
ctx.notifiers = []


def set_runtime_refs(coordinator, config: dict):
    """Called from main._cmd_serve_async to inject runtime instances."""
    ctx.coordinator = coordinator
    ctx.config = config


def set_scheduler(scheduler):
    """Called from main._cmd_serve_async to inject the APScheduler instance."""
    ctx.scheduler = scheduler


def set_notifiers(notifiers):
    """Called from main._cmd_serve_async to inject notification channels."""
    ctx.notifiers = notifiers or []


@app.post("/api/trigger-run")
async def api_trigger_run(
    site: str = Query(..., min_length=1),
    url: str = Query(..., min_length=1),
    use_browser: bool = Query(False),
):
    """Trigger a pipeline run for a specific site (async — returns immediately).

    The pipeline runs in background and results are broadcast via WebSocket
    when complete (see main.py _broadcast_on_run callback).
    """
    if ctx.coordinator is None:
        return JSONResponse({"error": "Coordinator not initialized"}, status_code=503)

    asyncio.create_task(ctx.coordinator.run_async(url, site, use_browser=use_browser))
    return {"status": "accepted", "site_name": site}


@app.post("/api/refresh-all")
async def api_refresh_all():
    """Trigger pipeline runs for all configured targets concurrently.
    Runs in background — WebSocket broadcasts results as each target completes."""
    if ctx.coordinator is None:
        return JSONResponse({"error": "Coordinator not initialized"}, status_code=503)

    asyncio.create_task(ctx.coordinator.run_all_targets_async())
    return {"status": "started", "message": "Refreshing all targets"}


@app.post("/api/reset")
async def api_reset(site: str = Query(..., min_length=1)):
    """Reset all history for a site (checks both news and papers DBs)."""
    is_paper = _is_article_site(site, _get_target_manager())

    db_paths = (
        [str(PAPERS_DB_PATH)]
        if is_paper
        else [
            ctx.config.get("storage", {}).get("db_path", "data/monitor.db")
            if ctx.config
            else str(DB_PATH),
            str(PAPERS_DB_PATH),
        ]
    )
    try:
        for db_path in db_paths:
            try:
                with sqlite3.connect(db_path) as conn:
                    conn.execute("DELETE FROM news_items WHERE site_name = ?", (site,))
                    conn.execute("DELETE FROM snapshots WHERE site_name = ?", (site,))
                    conn.execute("DELETE FROM run_logs WHERE site_name = ?", (site,))
                    conn.commit()
            except Exception as e:
                logger.warning(
                    "[API] Reset partially failed for %s (db %s): %s", site, db_path, e
                )
        return {
            "status": "ok",
            "site_name": site,
            "message": f"Reset history for {site}",
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── User behavior tracking ───────────────────────────────────────────


def _get_track_store():
    if ctx.track_store is None:
        ctx.track_store = TrackStore()
    return ctx.track_store


@app.post("/api/track")
async def api_track(request: Request):
    """Record a user behavior event (click, search, filter, etc.)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    event_type = (body.get("event_type") or "").strip()
    if not event_type:
        return JSONResponse({"error": "event_type is required"}, status_code=400)

    ts = _get_track_store()
    rid = ts.record(
        event_type=event_type,
        target_value=body.get("target_value", ""),
        metadata=body.get("metadata"),
    )
    return {"ok": True, "id": rid}


# ── Chat assistant ──────────────────────────────────────────────────


def _get_chat_agent():
    if ctx.chat_agent is None:
        from data.store import DataStore
        from data.episodic_memory import EpisodicMemory

        from agents.chat_agent import ChatAgent
        from agents.preference_engine import PreferenceEngine

        ctx.chat_agent = ChatAgent(
            ctx.config or {},
            news_store=DataStore(source_type="news"),
            paper_store=DataStore(source_type="paper"),
            vector_store=None,
            watch_store=_get_watch_store(),
            hybrid_searcher=_get_hybrid_searcher(),
            coordinator=ctx.coordinator,
            episodic_memory=EpisodicMemory(),
        )
        # Wire up PreferenceEngine with TrackStore
        engine = PreferenceEngine(track_store=_get_track_store())
        ctx.chat_agent._preference_engine = engine
        ctx.chat_agent._track_store = _get_track_store()
    return ctx.chat_agent


@app.post("/api/chat")
async def api_chat(request: Request):
    """Send a message to the chat assistant."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    session_id = body.get("session_id") or None
    agent = _get_chat_agent()
    result = await agent.chat(message, session_id=session_id)
    return result


@app.post("/api/chat/stream")
@limiter.limit("10/minute")
async def api_chat_stream(request: Request):
    """Send a message to the chat assistant with SSE streaming response."""
    from fastapi.responses import StreamingResponse

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    session_id = body.get("session_id") or None
    agent = _get_chat_agent()

    async def event_stream():
        async for chunk in agent.chat_stream(message, session_id=session_id):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _filter_history(messages: list) -> list:
    """Remove tool msgs and empty tool-call stubs; propagate tool_calls to
    next assistant so the frontend can render tool chips. Merge consecutive
    assistant messages into one."""
    pending_tool_calls = []
    filtered = []
    for m in messages:
        if m["role"] == "tool":
            continue
        if (
            m["role"] == "assistant"
            and not m.get("content", "").strip()
            and m.get("tool_calls")
        ):
            pending_tool_calls.extend(m["tool_calls"])
            continue
        m2 = m.copy()
        if m2["role"] == "assistant" and pending_tool_calls:
            m2["tool_calls"] = pending_tool_calls + m2.get("tool_calls", [])
            pending_tool_calls = []
        filtered.append(m2)
    # Merge consecutive assistant messages (propagate tool_calls too)
    merged = []
    for m in filtered:
        if merged and merged[-1]["role"] == "assistant" and m["role"] == "assistant":
            merged[-1]["content"] = (
                merged[-1]["content"] + "\n\n" + m.get("content", "")
            )
            if m.get("tool_calls"):
                tc = merged[-1].setdefault("tool_calls", [])
                tc.extend(m["tool_calls"])
        else:
            merged.append(m)
    return merged


@app.get("/api/chat/history")
async def api_chat_history(session_id: str | None = None):
    """Get current conversation history for a session."""
    agent = _get_chat_agent()
    if session_id:
        sid = agent._activate_session(session_id, create=False)
        if sid is None:
            return {"messages": [], "session_id": None, "not_found": True}
        return {"messages": _filter_history(list(agent._history)), "session_id": sid}
    return {"messages": [], "session_id": None}


@app.delete("/api/chat")
async def api_chat_clear(session_id: str | None = None):
    """Clear conversation history for a session."""
    _get_chat_agent().clear_history(session_id=session_id)
    return {"status": "cleared", "session_id": session_id}


@app.delete("/api/chat/sessions/{session_id}")
async def api_chat_delete_session(session_id: str):
    """Delete an entire chat session."""
    deleted = _get_chat_agent().delete_session(session_id)
    if not deleted:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/chat/context")
async def api_chat_context(session_id: str | None = None):
    """Get current context usage stats for a session."""
    agent = _get_chat_agent()
    if session_id:
        agent._activate_session(session_id, create=False)
    return agent.context_stats()


# ── Daily Report ──────────────────────────────────────────────────

ctx.report_last_result: dict | None = None


@app.post("/api/report/now")
async def api_report_now():
    """Trigger a daily report immediately and push via notifications."""
    agent = _get_chat_agent()
    cfg = (ctx.config or {}).get("chat", {}).get("auto_report", {})
    sites = cfg.get("include_sites") or [
        t.get("name") for t in (ctx.config or {}).get("targets", [])
    ]
    result = await agent.generate_daily_report(sites)
    ctx.report_last_result = result

    # Push via notification channels
    from notifications.dispatcher import PipelineEvent, notify_all

    event = PipelineEvent(
        site_name="all",
        url="",
        status="daily_report",
        items_count=result.get("stats", {}).get("total_items", 0),
        new_items=0,
        removed_items=0,
        modified_items=0,
        trend_direction="N/A",
        summary=result.get("report", ""),
        error=None,
        timestamp=result.get("generated_at", ""),
    )
    await notify_all(ctx.notifiers, event)
    return {"status": "sent", "report": result}


@app.get("/api/report/schedule")
async def api_report_schedule():
    """Get daily report schedule configuration."""
    cfg = (ctx.config or {}).get("chat", {}).get("auto_report", {})
    return {
        "enabled": cfg.get("enabled", False),
        "schedule_hour": cfg.get("schedule_hour", 9),
        "schedule_minute": cfg.get("schedule_minute", 0),
        "include_sites": cfg.get("include_sites") or "all",
        "last_report": ctx.report_last_result,
    }


@app.get("/api/chat/sessions")
async def api_chat_sessions():
    """List active chat sessions."""
    return {"sessions": _get_chat_agent().list_sessions()}


# ── Unified Watch API ──────────────────────────────────────────────


@app.get("/api/watches")
async def api_watches(
    type: str | None = Query(None),
    status: str | None = Query(None),
):
    """List all watches, optionally filtered by type and/or status."""
    store = _get_watch_store()
    watches = store.list_watches(
        watch_type=type if type else None,
        status=status if status else None,
        include_matches=True,
    )
    config = store.get_config()
    stale = store.get_stale_watches()
    return {
        "watches": watches,
        "count": len(watches),
        "config": config,
        "stale": stale,
    }


@app.get("/api/watches/{watch_id}")
async def api_watch_detail(watch_id: str):
    """Get a single watch with full match history."""
    store = _get_watch_store()
    w = store.get_watch(watch_id)
    if not w:
        return JSONResponse({"error": "Watch not found"}, status_code=404)
    return w


@app.get("/api/watches/{watch_id}/summary")
async def api_watch_summary(watch_id: str):
    """Get or generate latest match summary for a watch."""
    store = _get_watch_store()
    w = store.get_watch(watch_id)
    if not w:
        return JSONResponse({"error": "Watch not found"}, status_code=404)
    return {
        "watch_id": watch_id,
        "latest_summary": w.get("latest_summary"),
        "match_count": w.get("match_count", 0),
    }


@app.post("/api/watches/{watch_id}/complete")
async def api_watch_complete(watch_id: str):
    """Mark a watch as completed."""
    store = _get_watch_store()
    result = store.complete_watch(watch_id)
    if not result["ok"]:
        return JSONResponse({"error": result["msg"]}, status_code=404)
    return result


@app.post("/api/watches/{watch_id}/pause")
async def api_watch_pause(watch_id: str):
    """Pause a watch."""
    store = _get_watch_store()
    result = store.pause_watch(watch_id)
    if not result["ok"]:
        return JSONResponse({"error": result["msg"]}, status_code=404)
    return result


@app.post("/api/watches/{watch_id}/resume")
async def api_watch_resume(watch_id: str):
    """Resume a paused watch."""
    store = _get_watch_store()
    result = store.resume_watch(watch_id)
    if not result["ok"]:
        return JSONResponse({"error": result["msg"]}, status_code=404)
    return result


@app.delete("/api/watches/{watch_id}")
async def api_watch_remove(watch_id: str):
    """Remove a watch."""
    store = _get_watch_store()
    result = store.remove_watch(watch_id)
    if not result["ok"]:
        return JSONResponse({"error": result["msg"]}, status_code=404)
    return result


# ── Preferences & Memory API ────────────────────────────────────────


@app.get("/api/preferences")
async def api_preferences():
    """Return user preference data: L2 profile + L1 patterns + overrides."""
    agent = _get_chat_agent()
    engine = agent._preference_engine
    if engine is None:
        return {"l1": None, "l2": None, "overrides": {}, "display": "暂无偏好数据"}
    current = engine.get_current()
    overrides = engine.get_overrides()
    display = engine.format_for_display()
    return {
        "l1": current.get("l1"),
        "l2": current.get("l2"),
        "overrides": overrides,
        "display": display,
    }


@app.get("/api/memory/status")
async def api_memory_status():
    """Return memory system health: event counts, L0/L1/L2 status, episodic count."""
    from data.episodic_memory import EpisodicMemory

    ts = _get_track_store()
    stats = ts.get_stats(days=30)
    total = ts.total_count()
    l0_count = ts.get_l0_event_count_since("1970-01-01T00:00:00")

    em = EpisodicMemory()
    episodic_count = len(em._episodes)

    from pathlib import Path

    l1_path = Path("data/memory/l1_patterns.json")
    l2_path = Path("data/memory/l2_profile.json")
    overrides_path = Path("data/memory/explicit_overrides.json")

    l1_data = None
    l2_data = None
    overrides_data = None
    try:
        if l1_path.exists():
            l1_data = json.loads(l1_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        if l2_path.exists():
            l2_data = json.loads(l2_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        if overrides_path.exists():
            overrides_data = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    # Include MemoryManager internal state if available
    mm_status = None
    if ctx.memory_manager is not None:
        try:
            mm_status = ctx.memory_manager.get_status()
        except Exception:
            pass

    # Semantic cache stats
    cache_stats = {}
    try:
        from agents.semantic_cache import get_cache

        cache_stats = get_cache().stats()
    except Exception:
        pass

    return {
        "total_events": total,
        "stats_30d": stats,
        "l0_event_count": l0_count,
        "episodic_count": episodic_count,
        "l1": l1_data,
        "l2": l2_data,
        "overrides": overrides_data,
        "memory_manager": mm_status,
        "cache": cache_stats,
    }


# ── Recent Updates (replaces unreliable WebSocket push) ──────────


@app.get("/api/recent-updates")
async def api_recent_updates(
    since: int = Query(0, description="返回最近 N 条更新（0=全部）"),
):
    """Return recent pipeline update summaries stored in AppContext."""
    updates = ctx.recent_updates or []
    if since and since > 0:
        updates = updates[:since]
    return {"updates": updates, "total": len(ctx.recent_updates or [])}


# ── WebSocket ──────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = _get_effective_token()
    if token is not None:
        cookie_val = websocket.cookies.get("dashboard_token", "")
        if cookie_val != token:
            await websocket.close(code=4001, reason="unauthorized")
            return
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json(
                    {"type": "pong", "time": datetime.now().isoformat()}
                )
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)


async def broadcast_pipeline_update(data: dict):
    """Called from coordinator after each pipeline run."""
    ctx.last_run_time = datetime.now()
    await ws_manager.broadcast(data)


# ── Dashboard page ─────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/favicon.ico")
async def favicon():
    icon = PROJECT_ROOT / "web" / "templates" / "favicon.ico"
    if icon.exists():
        return FileResponse(str(icon))
    return Response(status_code=204)


@app.get("/api/health")
async def health():
    """Liveness/readiness probe for external monitoring."""
    uptime = (datetime.now() - _app_start).total_seconds()
    scheduler_running = ctx.scheduler is not None and ctx.scheduler.running
    return {
        "status": "ok",
        "uptime_seconds": round(uptime, 1),
        "scheduler_running": scheduler_running,
        "last_pipeline_run": ctx.last_run_time.isoformat()
        if ctx.last_run_time
        else None,
        "version": "0.6.0",
    }


@app.get("/api/cost")
async def api_cost(days: int = Query(7, ge=1, le=90)):
    """Return token usage aggregated by site over the last N days."""
    results = []
    if ctx.coordinator is not None:
        for store in [ctx.coordinator.store, ctx.coordinator.paper_store]:
            if store is not None:
                try:
                    results.extend(store.get_cost_summary(days=days))
                except Exception as e:
                    logger.warning("[API] Cost summary failed for store: %s", e)
    # Merge duplicate site entries (same site may appear in both stores)
    merged = {}
    for r in results:
        sn = r["site_name"]
        if sn in merged:
            merged[sn]["total_tokens"] += r["total_tokens"]
            merged[sn]["runs"] += r["runs"]
            merged[sn]["avg_tokens"] = round(
                merged[sn]["total_tokens"] / max(merged[sn]["runs"], 1), 1
            )
        else:
            merged[sn] = dict(r)
    total = sum(m["total_tokens"] for m in merged.values())
    return {
        "days": days,
        "total_tokens": total,
        "by_site": sorted(
            merged.values(), key=lambda x: x["total_tokens"], reverse=True
        ),
    }


@app.get("/api/cost/breakdown")
async def api_cost_breakdown(days: int = Query(30, ge=1, le=90)):
    """Daily token breakdown + cache stats."""
    daily = []
    if ctx.coordinator is not None:
        for store in [ctx.coordinator.store, ctx.coordinator.paper_store]:
            if store is not None:
                try:
                    daily.extend(store.get_cost_daily(days=days))
                except Exception as e:
                    logger.warning("[API] Cost daily failed for store: %s", e)

    # Merge duplicate days from both stores
    merged_daily = {}
    for d in daily:
        day = d["day"]
        if day in merged_daily:
            merged_daily[day]["total_tokens"] += d["total_tokens"]
            merged_daily[day]["runs"] += d["runs"]
        else:
            merged_daily[day] = dict(d)

    daily_list = sorted(merged_daily.values(), key=lambda x: x["day"], reverse=True)
    grand_total = sum(d["total_tokens"] for d in daily_list)

    # Semantic cache stats
    cache_stats = {}
    try:
        from agents.semantic_cache import get_cache

        cache_stats = get_cache().stats()
    except Exception:
        pass

    return {
        "days": days,
        "total_tokens": grand_total,
        "daily": daily_list,
        "cache": cache_stats,
    }
