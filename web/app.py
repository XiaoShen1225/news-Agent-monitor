"""FastAPI web dashboard for the news monitoring system."""

import logging
import sqlite3
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
PAPERS_DB_PATH = PROJECT_ROOT / "data" / "papers.db"
TEMPLATES_DIR = Path(__file__).parent / "templates"
VECTOR_DB_DIR = PROJECT_ROOT / "data" / "vector_db"

app = FastAPI(title="News Agent Monitor", version="0.6.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount chart directories as static
for chart_set in [
    "today",
    "yesterday",
    "two_days_ago",
    "one_week_ago",
    "one_month_ago",
    "total",
]:
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


def _get_papers_db():
    conn = sqlite3.connect(str(PAPERS_DB_PATH))
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
            "sentiment_distribution": [],
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

    all_snaps = store.get_all_snapshots(site_name)
    counts = [s.get("items_count", 0) for s in all_snaps]
    times = [s.get("timestamp", "") for s in all_snaps]

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
    """Return configured monitoring targets."""
    targets = _config.get("targets", []) if _config else []
    return {
        "targets": [
            {
                "name": t.get("name", ""),
                "url": t.get("url", ""),
                "use_browser": t.get("use_browser", False),
            }
            for t in targets
        ]
    }


@app.get("/api/papers")
async def api_papers(
    site: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Query papers/articles from article-type sources (uses separate papers.db)."""
    conn = _get_papers_db()
    try:
        article_sources = ["deepmind_blog", "openai_blog"]
        if site:
            source_list = [site] if site in article_sources else article_sources
        else:
            source_list = article_sources

        placeholders = ",".join("?" for _ in source_list)
        count_query = (
            f"SELECT COUNT(*) FROM news_items WHERE site_name IN ({placeholders})"
        )
        total_row = conn.execute(count_query, source_list).fetchone()
        total = total_row[0] if total_row else 0

        query = (
            f"SELECT title, url, tag, summary, snapshot_time, site_name FROM news_items "
            f"WHERE site_name IN ({placeholders}) "
            f"ORDER BY snapshot_time DESC LIMIT ? OFFSET ?"
        )
        rows = conn.execute(query, source_list + [limit, offset]).fetchall()
        items = [dict(r) for r in rows]

        sources = {}
        for s in source_list:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM news_items WHERE site_name = ?", (s,)
            ).fetchone()[0]
            sources[s] = cnt

        return {
            "items": items,
            "count": len(items),
            "total": total,
            "offset": offset,
            "limit": limit,
            "sources": sources,
        }
    finally:
        conn.close()


@app.get("/api/schedule")
async def api_schedule_status():
    """Return current scheduler status and config."""
    targets = _config.get("targets", []) if _config else []
    scheduler_cfg = _config.get("scheduler", {}) if _config else {}
    return {
        "targets": [
            {
                "name": t.get("name", ""),
                "url": t.get("url", ""),
                "interval_minutes": t.get(
                    "interval_minutes",
                    scheduler_cfg.get("default_interval_minutes", 60),
                ),
                "is_article": t.get("name", "")
                in ["deepmind_blog", "openai_blog", "google_ai_blog"],
            }
            for t in targets
        ],
        "default_interval": scheduler_cfg.get("default_interval_minutes", 60),
    }


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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
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

    # Get total count for pagination
    count_query = f"SELECT COUNT(*) FROM news_items {where}"
    conn = _get_db()
    try:
        total_row = conn.execute(count_query, params).fetchone()
        total = total_row[0] if total_row else 0

        query = (
            f"SELECT title, url, tag, summary, snapshot_time, site_name FROM news_items "
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

        return {
            "items": items,
            "count": len(items),
            "total": total,
            "offset": offset,
            "limit": limit,
            "tags": tags,
        }
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
    for cs in [
        "today",
        "yesterday",
        "two_days_ago",
        "one_week_ago",
        "one_month_ago",
        "total",
    ]:
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


@app.get("/api/summarize")
async def api_summarize(
    url: str = Query(..., min_length=1, description="Article URL to summarize"),
    title: str = Query("", description="Article title for context"),
):
    """Fetch article content and return an LLM-generated summary."""
    import os

    from agents.base_agent import BaseAgent

    api_key = os.environ.get("ZHIPU_API_KEY")
    if not api_key:
        return JSONResponse({"error": "LLM not configured"}, status_code=503)

    config = {
        "llm": {
            "api_key": api_key,
            "model": os.environ.get("ZHIPU_MODEL", "glm-4-flash"),
            "base_url": os.environ.get(
                "ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
            ),
        }
    }

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
        agent = BaseAgent("Summarizer", config)
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


# ── Action endpoints (CLI features in dashboard) ────────────────────

# Coordinator reference — set by _cmd_serve_async on startup
_coordinator = None
_config = None


def set_runtime_refs(coordinator, config: dict):
    """Called from main._cmd_serve_async to inject runtime instances."""
    global _coordinator, _config
    _coordinator = coordinator
    _config = config


@app.post("/api/trigger-run")
async def api_trigger_run(
    site: str = Query(..., min_length=1),
    url: str = Query(..., min_length=1),
    use_browser: bool = Query(False),
):
    """Trigger a pipeline run for a specific site."""
    if _coordinator is None:
        return JSONResponse({"error": "Coordinator not initialized"}, status_code=503)

    try:
        result = await _coordinator.run_async(url, site, use_browser=use_browser)
        return {
            "status": result.get("status"),
            "site_name": site,
            "items_found": result.get("report", {}).get("current_count", 0)
            if result.get("report")
            else 0,
            "timestamp": result.get("report", {}).get("timestamp", "")
            if result.get("report")
            else "",
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/reset")
async def api_reset(site: str = Query(..., min_length=1)):
    """Reset all history for a site (checks both news and papers DBs)."""
    import sqlite3

    paper_sources = {"deepmind_blog", "openai_blog"}
    is_paper = site in paper_sources

    db_paths = (
        [str(PAPERS_DB_PATH)]
        if is_paper
        else [
            _config.get("storage", {}).get("db_path", "data/monitor.db")
            if _config
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
            except Exception:
                pass
        return {
            "status": "ok",
            "site_name": site,
            "message": f"Reset history for {site}",
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── WebSocket ──────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json(
                    {"type": "pong", "time": datetime.now().isoformat()}
                )
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
    icon = PROJECT_ROOT / "web" / "templates" / "favicon.ico"
    return (
        FileResponse(str(icon))
        if icon.exists()
        else JSONResponse(None, status_code=204)
    )
