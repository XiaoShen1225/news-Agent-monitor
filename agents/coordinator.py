"""CoordinatorAgent: orchestrates the full multi-agent pipeline — sync + async."""

import asyncio
import json
import logging
import time
import uuid

from .base_agent import BaseAgent
from .fetcher import FetcherAgent
from .parser import ParserAgent
from .analyzer import AnalyzerAgent
from .visualizer import VisualizationAgent
from .sentiment_analyzer import classify
from .site_profiles import SiteProfile, get_profile
from data.alert_store import AlertStore
from notifications.dispatcher import build_event, notify_all

logger = logging.getLogger(__name__)


class CoordinatorAgent(BaseAgent):
    """Orchestrates Fetcher → Parser → Analyzer → Visualizer pipeline."""

    def __init__(
        self,
        config: dict,
        data_store=None,
        paper_store=None,
        evolution=None,
        notifiers=None,
        vector_store=None,
    ):
        super().__init__("Coordinator", config)
        self.config = config
        self.fetcher = FetcherAgent(config)
        self.parser = ParserAgent(config)
        self.analyzer = AnalyzerAgent(config, data_store)
        self.visualizer = VisualizationAgent(config)
        self.store = data_store
        self.paper_store = paper_store or data_store
        self.evolution = evolution
        self.notifiers = notifiers or []
        self.vector_store = vector_store
        self.alert_store = AlertStore()
        self.alert_store.load_config(config)
        self.max_snapshots = config.get("storage", {}).get("max_snapshots_per_site", 0)

    # ── sync (wraps async) ──────────────────────────────────────────

    def run(
        self, url: str, site_name: str = "default", use_browser: bool = False
    ) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(url, site_name, use_browser))
        raise RuntimeError("Coordinator.run() in async context — use run_async()")

    def run_all_targets(self) -> list:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_all_targets_async())
        raise RuntimeError(
            "Coordinator.run_all_targets() in async context — use run_all_targets_async()"
        )

    # ── async single target ─────────────────────────────────────────

    async def run_async(
        self,
        url: str,
        site_name: str = "default",
        use_browser: bool = False,
        profile: SiteProfile = None,
    ) -> dict:
        profile = profile or get_profile(site_name)
        is_article = profile.is_article_source if profile else False
        active_store = self.paper_store if is_article else self.store

        trace_id = uuid.uuid4().hex[:12]
        start_time = time.time()
        result = {
            "site_name": site_name,
            "url": url,
            "status": "unknown",
            "error": None,
            "report": None,
            "charts": None,
        }

        # Circuit breaker: skip sites that have failed too many times in a row
        if active_store and active_store.is_circuit_open(site_name):
            logger.warning(
                json.dumps(
                    {
                        "event": "pipeline_skip",
                        "trace_id": trace_id,
                        "site": site_name,
                        "reason": "circuit_open",
                    }
                )
            )
            result["status"] = "circuit_open"
            return result

        logger.info(
            json.dumps(
                {
                    "event": "pipeline_start",
                    "trace_id": trace_id,
                    "site": site_name,
                    "url": url,
                }
            )
        )

        try:
            # Step 1: Fetch
            fetch_result = await self.fetcher.run_async(url, use_browser=use_browser)
            content_hash = fetch_result["content_hash"]

            # Step 2: Check if content changed
            last_hash = active_store.get_last_hash(site_name) if active_store else None
            if last_hash == content_hash and last_hash is not None:
                elapsed = (time.time() - start_time) * 1000
                logger.info(
                    json.dumps(
                        {
                            "event": "pipeline_skip",
                            "trace_id": trace_id,
                            "site": site_name,
                            "reason": "no_change",
                            "duration_ms": round(elapsed),
                        }
                    )
                )
                result["status"] = "skipped_no_change"
                result["report"] = {
                    "site_name": site_name,
                    "content_hash": content_hash,
                    "has_changes": False,
                    "is_first_run": False,
                }
                if active_store:
                    active_store.reset_failure(site_name)
                    active_store.log_run(
                        site_name,
                        "skipped_no_change",
                        processing_time_ms=elapsed,
                        trace_id=trace_id,
                    )
                return result

            # Step 3: Parse (with site profile) — async for LLM strategy support
            parse_result = await self.parser.run_async(
                fetch_result["html"],
                site_name,
                url,
                profile,
            )
            items = parse_result["items"]
            confidence = parse_result["extraction_confidence"]

            # Step 3b: Enrich items without published time from article pages
            items = await self.parser.enrich_times(items)
            # For browser-based sites, use Playwright to enrich baidu-domain articles
            if use_browser:
                items = await self._enrich_times_browser(items)

            # Step 3c: Sentiment labeling (rule-based, no LLM cost)
            for item in items:
                if not item.get("sentiment"):
                    item["sentiment"] = classify(item.get("title", ""))

            # Step 4: Analyze
            report = await self.analyzer.run_async(
                items, site_name, content_hash, store=active_store
            )

            # Step 5: Save snapshot
            if active_store:
                active_store.save_snapshot(site_name, url, content_hash, items)
                # Update metadata for fast dashboard queries
                active_store.update_metadata(
                    site_name,
                    items_count=len(items),
                    tag_dist=report.get("tag_distribution", {}),
                    changes={
                        "new": len(report.get("new_items", [])),
                        "removed": len(report.get("removed_items", [])),
                        "modified": len(report.get("modified_items", [])),
                    },
                    update_summary=report.get("update_summary") or "",
                )
                # Prune old snapshots
                if self.max_snapshots > 0:
                    active_store.prune_snapshots(site_name, self.max_snapshots)
                # Index items in vector store for semantic search
                if self.vector_store:
                    try:
                        self.vector_store.add_items(items, site_name)
                    except Exception as e:
                        logger.warning("Vector store indexing failed: %s", e)

            # Step 6: Get snapshots for trends
            snapshots = (
                active_store.get_all_snapshots(site_name) if active_store else []
            )

            # Step 7: Visualize (skip for article sources)
            if is_article:
                chart_result = None
            else:
                chart_result = await asyncio.to_thread(
                    self.visualizer.run, report, snapshots
                )

            # Step 8: Record evolution
            if self.evolution:
                total_tokens_evo = (
                    self.parser.get_last_tokens() + self.analyzer.get_last_tokens()
                )
                self.evolution.record_run(
                    site_name,
                    report,
                    confidence,
                    (time.time() - start_time) * 1000,
                    total_tokens=total_tokens_evo,
                )

            result["status"] = "success"
            result["report"] = report
            result["charts"] = chart_result

            # ── Alert matching ────────────────────────────────────────
            alert_config = self.config.get("alerts", {}) or {}
            new_items = report.get("new_items", [])

            # Keyword matching
            alert_matches = self.alert_store.match_items(new_items)
            result["alert_matches"] = alert_matches

            # Anomaly detection cooldown check
            anomalies = report.get("anomalies", [])
            result["anomalies"] = []
            anomaly_cfg = alert_config.get("anomaly", {})
            cooldown_min = anomaly_cfg.get("cooldown_minutes", 120)
            for a in anomalies:
                if self.alert_store.should_alert_anomaly(
                    site_name, a["type"], cooldown_min
                ):
                    result["anomalies"].append(a)
                    self.alert_store.log_anomaly_alert(
                        site_name,
                        a["type"],
                        f"{a['type']}: current={a['current_count']}, baseline={a['baseline_avg']}",
                    )

            # Sentiment shift check
            sentiment_shift = report.get("sentiment_shift", {}) or {}
            if sentiment_shift.get("significant"):
                result["sentiment_shift"] = sentiment_shift
                self.alert_store.log_sentiment_shift(
                    site_name, f"情感偏移: {sentiment_shift.get('shifted', {})}"
                )
            else:
                result["sentiment_shift"] = None

            elapsed = (time.time() - start_time) * 1000
            total_tokens = (
                self.parser.get_last_tokens() + self.analyzer.get_last_tokens()
            )
            logger.info(
                json.dumps(
                    {
                        "event": "pipeline_done",
                        "trace_id": trace_id,
                        "site": site_name,
                        "duration_ms": round(elapsed),
                        "items": len(items),
                        "changes": report.get("total_changes", 0),
                        "tokens": total_tokens,
                    }
                )
            )

            if active_store:
                active_store.reset_failure(site_name)
                active_store.log_run(
                    site_name,
                    "success",
                    items_found=len(items),
                    changes_detected=report.get("total_changes", 0),
                    extraction_confidence=confidence,
                    processing_time_ms=elapsed,
                    trace_id=trace_id,
                    total_tokens=total_tokens,
                )

            await notify_all(self.notifiers, build_event(result))

        except Exception as e:
            import traceback

            elapsed = (time.time() - start_time) * 1000
            error_str = str(e)
            logger.error(
                json.dumps(
                    {
                        "event": "pipeline_error",
                        "trace_id": trace_id,
                        "site": site_name,
                        "error": error_str,
                        "duration_ms": round(elapsed),
                    }
                )
            )
            logger.error("[Coordinator] Traceback:\n%s", traceback.format_exc())
            result["status"] = "error"
            result["error"] = str(e)

            if active_store:
                is_open = active_store.increment_failure(site_name)
                if is_open:
                    logger.warning(
                        "[Coordinator] Circuit breaker OPEN for %s — will skip for 1 hour",
                        site_name,
                    )
                active_store.log_run(
                    site_name,
                    "error",
                    error_message=str(e),
                    processing_time_ms=elapsed,
                    trace_id=trace_id,
                )

            await notify_all(self.notifiers, build_event(result))

        return result

    # ── Article time enrichment via Playwright ─────────────────────────

    async def _enrich_times_browser(self, items: list, max_fetch: int = 15) -> list:
        """Use Playwright browser to fetch article pages and extract publication times."""
        import re

        need_enrich = [(i, it) for i, it in enumerate(items) if not it.get("published")]
        if not need_enrich:
            return items

        limit = min(len(need_enrich), max_fetch)
        time_pat = re.compile(
            r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?)"
        )

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                enriched = 0

                for _, item in need_enrich[:limit]:
                    try:
                        await page.goto(
                            item["url"],
                            timeout=15000,
                            wait_until="domcontentloaded",
                        )
                        await page.wait_for_timeout(1000)
                        text = await page.evaluate("() => document.body.innerText")
                        m = time_pat.search(text[:5000])
                        if m:
                            item["published"] = m.group(1)
                            enriched += 1
                    except Exception:
                        pass

                await browser.close()
                logger.info(
                    "[Coordinator] Browser-enriched %d/%d items with times",
                    enriched,
                    limit,
                )
        except Exception as e:
            logger.warning("[Coordinator] Browser time enrichment failed: %s", e)

        return items

    # ── async multi-target (concurrent) ─────────────────────────────

    async def run_all_targets_async(self) -> list:
        targets = self.config.get("targets", [])
        if not targets:
            return []

        tasks = []
        for target in targets:
            profile = target.get("profile")
            profile_obj = SiteProfile.from_dict(profile) if profile else None
            tasks.append(
                self.run_async(
                    target["url"],
                    target["name"],
                    use_browser=target.get("use_browser", False),
                    profile=profile_obj,
                )
            )

        logger.info("[Coordinator] Running %d targets concurrently", len(tasks))
        return await asyncio.gather(*tasks, return_exceptions=True)
