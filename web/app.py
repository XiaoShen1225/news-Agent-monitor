"""FastAPI web dashboard for the news monitoring system."""

import logging
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
CHARTS_DIR = OUTPUTS_DIR / "charts"
DB_PATH = PROJECT_ROOT / "data" / "monitor.db"
TEMPLATES_DIR = Path(__file__).parent / "templates"
VECTOR_DB_DIR = PROJECT_ROOT / "data" / "vector_db"

app = FastAPI(title="News Agent Monitor", version="0.6.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount chart directories as static
for chart_set in ["today", "yesterday", "two_days_ago", "one_week_ago",
                   "one_month_ago", "total"]:
    chart_dir = CHARTS_DIR / chart_set
    chart_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        f"/charts/{chart_set}",
        StaticFiles(directory=str(chart_dir)),
        name=f"charts_{chart_set}",
    )


# ── WebSocket manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        disconnected = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.active.remove(ws)


ws_manager = ConnectionManager()

# Shared VectorStore instance — loading the embedding model is expensive,
# so reuse a single instance across all /api/search requests.
_shared_vector_store = None


def _get_vector_store():
    global _shared_vector_store
    if _shared_vector_store is None:
        from data.vector_store import VectorStore
        _shared_vector_store = VectorStore(str(VECTOR_DB_DIR))
    return _shared_vector_store


# ── helpers ────────────────────────────────────────────────────────

def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _get_sites() -> list:
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT DISTINCT site_name FROM snapshots ORDER BY site_name"
        ).fetchall()
        conn.close()
        return [r["site_name"] for r in rows]
    except Exception:
        return []


def _get_data_store():
    """Create a DataStore instance pointing at the project data dirs."""
    from data.store import DataStore
    return DataStore(
        history_dir=str(PROJECT_ROOT / "data" / "history"),
        db_path=str(DB_PATH),
    )


def _diff_items(prev_items: list, curr_items: list) -> dict:
    """Compare two item lists by title; return new/removed/modified counts."""
    prev_titles = {it.get("title", ""): it for it in prev_items}
    curr_titles = {it.get("title", ""): it for it in curr_items}
    new = sum(1 for t in curr_titles if t and t not in prev_titles)
    removed = sum(1 for t in prev_titles if t and t not in curr_titles)
    modified = 0
    for t in curr_titles:
        if t and t in prev_titles:
            p, c = prev_titles[t], curr_titles[t]
            if p.get("tag") != c.get("tag") or p.get("summary") != c.get("summary"):
                modified += 1
    return {"new": new, "removed": removed, "modified": modified}


def _build_chart_data(site_name: str, store) -> dict:
    """Build ECharts-friendly data dict for a single site from persisted snapshots."""
    snap = store.get_last_snapshot(site_name)
    if not snap:
        return None

    items = snap.get("items", [])

    # Tag distribution
    tag_dist = {}
    for item in items:
        t = item.get("tag", "其他") or "其他"
        tag_dist[t] = tag_dist.get(t, 0) + 1
    tag_list = [{"name": k, "value": v} for k, v in
                sorted(tag_dist.items(), key=lambda x: x[1], reverse=True)]

    # Trends from all snapshots
    all_snaps = store.get_all_snapshots(site_name)
    counts = [s.get("items_count", 0) for s in all_snaps]
    times = [s.get("timestamp", "") for s in all_snaps]

    direction = "stable"
    recent_avg = 0
    older_avg = 0
    if len(counts) >= 2:
        recent_avg = sum(counts[-3:]) / min(3, len(counts[-3:]))
        older_avg = sum(counts[:max(1, len(counts) - 3)]) / max(1, len(counts) - 3)
        if recent_avg > older_avg * 1.1:
            direction = "up"
        elif recent_avg < older_avg * 0.9:
            direction = "down"

    # Changes: diff two most recent snapshots
    changes = {"new": 0, "removed": 0, "modified": 0}
    if len(all_snaps) >= 2:
        prev_items = all_snaps[-2].get("items", [])
        changes = _diff_items(prev_items, items)

    # Sentiment distribution
    sent_dist = {}
    for item in items:
        s = item.get("sentiment") or "unknown"
        sent_dist[s] = sent_dist.get(s, 0) + 1
    sent_list = [{"name": k, "value": v} for k, v in sent_dist.items()]

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
        "sentiment_distribution": sent_list,
        "summary": {
            "site_name": site_name,
            "timestamp": snap.get("timestamp", ""),
            "current_count": len(items),
            "previous_count": all_snaps[-2].get("items_count", 0) if len(all_snaps) >= 2 else 0,
            "total_changes": changes["new"] + changes["removed"] + changes["modified"],
            "trend_direction": direction,
            "llm_summary": None,
            "new_count": changes["new"],
            "removed_count": changes["removed"],
            "modified_count": changes["modified"],
        },
    }


# ── REST API ───────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats(
    site: Optional[str] = Query(None),
):
    conn = _get_db()
    try:
        # Run logs
        if site:
            rows = conn.execute(
                "SELECT status, items_found, changes_detected, extraction_confidence, "
                "processing_time_ms, created_at FROM run_logs "
                "WHERE site_name = ? ORDER BY id DESC LIMIT 20",
                (site,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT site_name, status, items_found, changes_detected, "
                "processing_time_ms, created_at FROM run_logs "
                "ORDER BY id DESC LIMIT 50"
            ).fetchall()

        runs = [dict(r) for r in rows]

        # Latest snapshot per site
        sites = _get_sites()
        snapshots = {}
        for s in sites:
            row = conn.execute(
                "SELECT items_count, created_at FROM snapshots "
                "WHERE site_name = ? ORDER BY id DESC LIMIT 1",
                (s,),
            ).fetchone()
            if row:
                snapshots[s] = dict(row)

        return {"runs": runs, "snapshots": snapshots, "sites": sites}
    finally:
        conn.close()


@app.get("/api/query")
async def api_query(
    site: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    conditions = []
    params = []
    if site:
        conditions.append("site_name = ?")
        params.append(site)
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
    query = (
        f"SELECT title, url, tag, snapshot_time, site_name FROM news_items "
        f"{where} ORDER BY snapshot_time DESC LIMIT ?"
    )
    params.append(limit)

    conn = _get_db()
    try:
        rows = conn.execute(query, params).fetchall()
        items = [dict(r) for r in rows]

        # Tag distribution
        tags = Counter(it["tag"] for it in items)
        return {"items": items, "count": len(items), "tags": dict(tags.most_common(20))}
    finally:
        conn.close()


@app.get("/api/search")
async def api_search(
    q: str = Query(..., min_length=1, description="Search query"),
    site: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """Semantic search over news items using vector embeddings."""
    vs = _get_vector_store()
    results = vs.search(q, site_name=site, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/charts")
async def api_charts():
    chart_sets = {}
    for cs in ["today", "yesterday", "two_days_ago",
               "one_week_ago", "one_month_ago", "total"]:
        chart_dir = CHARTS_DIR / cs
        if chart_dir.exists():
            files = sorted(
                [f.name for f in chart_dir.glob("*.png")],
                key=lambda x: ("overview" in x, "trend" in x, "pie" in x, x),
            )
            if files:
                chart_sets[cs] = files
    return chart_sets


@app.get("/api/chart-data")
async def api_chart_data(
    site: Optional[str] = Query(None),
):
    """Return structured chart data for ECharts rendering."""
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

    return {"sites": sites, "chart_data": chart_data}


# ── WebSocket ──────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong", "time": datetime.now().isoformat()})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


async def broadcast_pipeline_update(data: dict):
    """Called from coordinator after each pipeline run."""
    await ws_manager.broadcast(data)


# ── Dashboard page ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(str(PROJECT_ROOT / "web" / "templates" / "favicon.ico")) \
        if (PROJECT_ROOT / "web" / "templates" / "favicon.ico").exists() \
        else JSONResponse({}, status_code=404)
