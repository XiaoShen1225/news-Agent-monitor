"""Main entry point: CLI for the Data Visualization monitoring system.

Usage:
    python main.py --once --url https://news.example.com [--name mysite]
    python main.py --schedule
    python main.py --reset --name mysite
    python main.py --stats --name mysite
"""

import argparse
import asyncio
import logging
import os
import re
import signal
import sys
from pathlib import Path

import yaml

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file
def _load_dotenv():
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if key not in os.environ:
                        os.environ[key] = value

_load_dotenv()

from data.store import DataStore  # noqa: E402
from evolution.memory import EvolutionMemory  # noqa: E402
from evolution.optimizer import EvolutionOptimizer  # noqa: E402
from agents.coordinator import CoordinatorAgent  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


_ENV_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")

def _resolve_env(value):
    """Recursively resolve ${VAR} placeholders in config values."""
    if isinstance(value, str):
        def _repl(m):
            return os.environ.get(m.group(1), "")
        return _ENV_PLACEHOLDER.sub(_repl, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value

def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _resolve_env(raw)


def print_summary(result: dict, charts: dict = None):
    """Print a formatted summary of the pipeline result."""
    report = result.get("report", {})
    status = result.get("status", "unknown")

    print("\n" + "=" * 60)
    print(f"  Site: {result.get('site_name', '?')}  |  Status: {status}")
    print("=" * 60)

    if status == "error":
        print(f"  Error: {result.get('error', 'unknown')}")
        return

    if status == "skipped_no_change":
        print("  No content change detected. Skipped LLM processing.")
        return

    if report:
        print(f"  Items extracted: {report.get('current_count', 0)}")
        print(f"  New: {len(report.get('new_items', []))}  "
              f"Removed: {len(report.get('removed_items', []))}  "
              f"Modified: {len(report.get('modified_items', []))}")
        print(f"  Trend direction: {report.get('trends', {}).get('direction', 'N/A')}")
        print(f"  Tag distribution: {report.get('tag_distribution', {})}")

        summary = report.get("llm_summary")
        if summary:
            print(f"\n  [AI Summary] {summary}")

    if charts:
        chart_map = charts.get("charts", {})
        if chart_map:
            print(f"\n  Charts generated ({len(chart_map)}):")
            for name, path in sorted(chart_map.items()):
                print(f"    - {name}: {path}")

    print("=" * 60)


def cmd_once(config: dict, url: str, name: str):
    """Run a single monitoring pass."""
    store = DataStore(
        history_dir=config.get("storage", {}).get("history_dir", "data/history"),
        db_path=config.get("storage", {}).get("db_path", "data/monitor.db"),
    )

    memory = EvolutionMemory()
    optimizer = EvolutionOptimizer(config, memory) if config.get("evolution", {}).get("enabled") else None

    # Look up target config for use_browser etc.
    use_browser = False
    for t in config.get("targets", []):
        if t.get("name") == name:
            use_browser = t.get("use_browser", False)
            break

    coordinator = CoordinatorAgent(config, data_store=store, evolution=optimizer)
    result = coordinator.run(url, name, use_browser=use_browser)

    print_summary(result, result.get("charts"))
    return result


def cmd_schedule(config: dict):
    """Run in scheduled mode for all configured targets (async)."""
    asyncio.run(_cmd_schedule_async(config))


async def _cmd_schedule_async(config: dict):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    store = DataStore(
        history_dir=config.get("storage", {}).get("history_dir", "data/history"),
        db_path=config.get("storage", {}).get("db_path", "data/monitor.db"),
    )
    memory = EvolutionMemory()
    optimizer = EvolutionOptimizer(config, memory) if config.get("evolution", {}).get("enabled") else None
    coordinator = CoordinatorAgent(config, data_store=store, evolution=optimizer)

    scheduler = AsyncIOScheduler()
    targets = config.get("targets", [])

    if not targets:
        logger.error("No targets configured in config.yaml")
        return

    default_interval = config.get("scheduler", {}).get("default_interval_minutes", 60)

    # Run initial fetch for all targets concurrently
    logger.info("Running initial fetch for %d targets...", len(targets))
    try:
        results = await coordinator.run_all_targets_async()
        for target, result in zip(targets, results):
            name = target["name"]
            if isinstance(result, Exception):
                logger.error("Initial fetch for '%s' failed: %s", name, result)
            else:
                logger.info("Initial fetch for '%s': %s", name, result.get("status", "?"))
    except Exception as e:
        logger.error("Initial batch fetch failed: %s", e)

    for target in targets:
        interval = target.get("interval_minutes", default_interval)
        scheduler.add_job(
            coordinator.run_async,
            "interval",
            minutes=interval,
            kwargs={
                "url": target["url"],
                "site_name": target["name"],
                "use_browser": target.get("use_browser", False),
            },
            id=f"monitor_{target['name']}",
            name=f"Monitor {target['name']}",
        )
        logger.info("Scheduled '%s': every %d min → %s", target["name"], interval, target["url"])

    logger.info("Scheduler started. Press Ctrl+C to stop.")
    print("\n" + "=" * 60)
    print("  Monitor Running")
    print("=" * 60)
    for t in targets:
        print(f"  {t['name']}: every {t.get('interval_minutes', default_interval)} min → {t['url']}")
    print("  Press Ctrl+C to stop")
    print("=" * 60 + "\n")

    try:
        await scheduler.start()
        # Keep running until interrupted
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, lambda: stop_event.set())
        loop.add_signal_handler(signal.SIGTERM, lambda: stop_event.set())
        await stop_event.wait()
        scheduler.shutdown(wait=False)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped.")


def cmd_serve(config: dict, port: int = 8080):
    """Start web dashboard + background scheduler."""
    asyncio.run(_cmd_serve_async(config, port))


async def _cmd_serve_async(config: dict, port: int):
    import uvicorn
    from web.app import app, ws_manager

    store = DataStore(
        history_dir=config.get("storage", {}).get("history_dir", "data/history"),
        db_path=config.get("storage", {}).get("db_path", "data/monitor.db"),
    )
    memory = EvolutionMemory()
    optimizer = EvolutionOptimizer(config, memory) if config.get("evolution", {}).get("enabled") else None
    coordinator = CoordinatorAgent(config, data_store=store, evolution=optimizer)

    targets = config.get("targets", [])
    if not targets:
        logger.error("No targets configured in config.yaml")
        return

    # Patch coordinator to broadcast after each run
    original_run = coordinator.run_async

    async def run_with_broadcast(url, site_name="default", use_browser=False, profile=None):
        result = await original_run(url, site_name, use_browser, profile)
        try:
            await ws_manager.broadcast({
                "type": "pipeline_update",
                "site_name": site_name,
                "status": result.get("status"),
                "items": result.get("report", {}).get("current_count", 0),
                "time": result.get("report", {}).get("timestamp", ""),
            })
        except Exception:
            pass
        return result

    coordinator.run_async = run_with_broadcast
    coordinator.run_all_targets_async = lambda: asyncio.gather(*[
        run_with_broadcast(t["url"], t["name"], t.get("use_browser", False))
        for t in targets
    ], return_exceptions=True)

    # Start scheduler in background task
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    default_interval = config.get("scheduler", {}).get("default_interval_minutes", 60)

    logger.info("Running initial fetch for %d targets...", len(targets))
    try:
        await coordinator.run_all_targets_async()
    except Exception as e:
        logger.error("Initial batch fetch failed: %s", e)

    for target in targets:
        interval = target.get("interval_minutes", default_interval)
        scheduler.add_job(
            run_with_broadcast,
            "interval",
            minutes=interval,
            kwargs={
                "url": target["url"],
                "site_name": target["name"],
                "use_browser": target.get("use_browser", False),
            },
            id=f"monitor_{target['name']}",
            name=f"Monitor {target['name']}",
        )

    scheduler.start()

    print("\n" + "=" * 60)
    print(f"  Dashboard: http://localhost:{port}")
    print(f"  API Docs:  http://localhost:{port}/docs")
    print("=" * 60)
    for t in targets:
        print(f"  {t['name']}: every {t.get('interval_minutes', default_interval)} min → {t['url']}")
    print("=" * 60 + "\n")

    config_obj = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config_obj)
    await server.serve()


def cmd_stats(config: dict, name: str):
    """Show statistics for a monitored site."""
    store = DataStore(
        history_dir=config.get("storage", {}).get("history_dir", "data/history"),
        db_path=config.get("storage", {}).get("db_path", "data/monitor.db"),
    )
    memory = EvolutionMemory()

    print("\n" + "=" * 60)
    print(f"  Statistics for: {name}")
    print("=" * 60)

    # Evolution stats
    stats = memory.get_stats(name)
    print(f"  Total runs: {stats.get('runs', 0)}")
    if stats.get("runs", 0) > 0:
        print(f"  Avg extraction confidence: {stats.get('avg_confidence', 0)}")
        print(f"  Avg processing time: {stats.get('avg_time_ms', 0):.0f} ms")
        print(f"  Avg changes per run: {stats.get('avg_changes_per_run', 0)}")
        print(f"  Change frequency: {stats.get('change_frequency', 0):.0%}")

    # DB run logs
    runs = store.get_run_history(name, limit=10)
    if runs:
        print("\n  Recent runs:")
        for r in runs[:10]:
            status_icon = "✓" if r["status"] == "success" else ("○" if "skip" in r["status"] else "✗")
            print(f"    {status_icon} {r['created_at']} | items={r['items_found']} "
                  f"changes={r['changes_detected']} conf={r['extraction_confidence']:.2f}")

    # Latest snapshot
    snap = store.get_last_snapshot(name)
    if snap:
        print(f"\n  Latest snapshot: {snap.get('timestamp', '?')}")
        print(f"  Items in snapshot: {snap.get('items_count', 0)}")

    print("=" * 60)


def cmd_reset(config: dict, name: str):
    """Reset history for a site."""
    import sqlite3
    db_path = config.get("storage", {}).get("db_path", "data/monitor.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM news_items WHERE site_name = ?", (name,))
        conn.execute("DELETE FROM snapshots WHERE site_name = ?", (name,))
        conn.execute("DELETE FROM run_logs WHERE site_name = ?", (name,))
        conn.commit()
    print(f"Reset history for: {name}")


def cmd_query(config: dict, name: str, tag: str = None, date_from: str = None,
              date_to: str = None, limit: int = 100):
    """Query news items from the database."""
    store = DataStore(
        history_dir=config.get("storage", {}).get("history_dir", "data/history"),
        db_path=config.get("storage", {}).get("db_path", "data/monitor.db"),
    )

    items = store.query_items(
        site_name=name if name != "default" else None,
        tag=tag, date_from=date_from, date_to=date_to, limit=limit,
    )

    if not items:
        print("No items found matching the criteria.")
        return

    # Tag distribution
    from collections import Counter
    tags = Counter(it["tag"] for it in items)

    print("\n" + "=" * 60)
    print(f"  Query Results: {len(items)} items")
    if tag:
        print(f"  Tag filter: {tag}")
    if date_from or date_to:
        print(f"  Date range: {date_from or 'any'} ~ {date_to or 'any'}")
    print(f"  Tag distribution: {dict(tags.most_common(10))}")
    print("=" * 60)

    for i, it in enumerate(items[:30], 1):
        print(f"\n  [{i}] [{it['tag']}] {it['title'][:80]}")
        print(f"      {it['url'][:90]}")
        print(f"      {it['snapshot_time'][:19]}")

    if len(items) > 30:
        print(f"\n  ... and {len(items) - 30} more items.")


def main():
    parser = argparse.ArgumentParser(
        description="Data Visualization Monitor - Multi-agent web content tracker"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--schedule", action="store_true", help="Run in scheduled mode")
    parser.add_argument("--serve", action="store_true", help="Start web dashboard + scheduler")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard port (default: 8080)")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--reset", action="store_true", help="Reset history for a site")
    parser.add_argument("--query", action="store_true", help="Query news items from database")
    parser.add_argument("--tag", help="Filter by tag (for --query)")
    parser.add_argument("--from", dest="date_from", help="Filter from date YYYY-MM-DD (for --query)")
    parser.add_argument("--to", dest="date_to", help="Filter to date YYYY-MM-DD (for --query)")
    parser.add_argument("--limit", type=int, default=100, help="Max items to return (for --query)")
    parser.add_argument("--url", help="Target URL for --once mode")
    parser.add_argument("--name", default="default", help="Site name identifier")
    parser.add_argument("--interval", type=int, help="Override schedule interval (minutes)")

    args = parser.parse_args()

    if not Path(args.config).exists():
        print(f"Config file not found: {args.config}")
        print("Copy config.yaml and edit it with your settings.")
        sys.exit(1)

    config = load_config(args.config)

    # Override from CLI
    if args.interval:
        for target in config.get("targets", []):
            target["interval_minutes"] = args.interval

    if args.reset:
        cmd_reset(config, args.name)
    elif args.query:
        cmd_query(config, args.name, tag=args.tag, date_from=args.date_from,
                  date_to=args.date_to, limit=args.limit)
    elif args.stats:
        cmd_stats(config, args.name)
    elif args.once:
        url = args.url
        if not url:
            targets = config.get("targets", [])
            if targets:
                url = targets[0]["url"]
                if not args.name or args.name == "default":
                    args.name = targets[0].get("name", "default")
            else:
                print("No URL provided. Use --url or configure targets in config.yaml")
                sys.exit(1)
        cmd_once(config, url, args.name)
    elif args.schedule:
        cmd_schedule(config)
    elif args.serve:
        cmd_serve(config, args.port)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python main.py --once --url https://news.baidu.com --name baidu_news")
        print("  python main.py --schedule")
        print("  python main.py --stats --name baidu_news")
        print("  python main.py --reset --name baidu_news")


if __name__ == "__main__":
    main()
