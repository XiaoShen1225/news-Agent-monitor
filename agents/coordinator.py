"""CoordinatorAgent: orchestrates the full multi-agent pipeline — sync + async."""

import asyncio
import logging
import time

from .base_agent import BaseAgent
from .fetcher import FetcherAgent
from .parser import ParserAgent
from .analyzer import AnalyzerAgent
from .visualizer import VisualizationAgent
from .site_profiles import SiteProfile, get_profile

logger = logging.getLogger(__name__)


class CoordinatorAgent(BaseAgent):
    """Orchestrates Fetcher → Parser → Analyzer → Visualizer pipeline."""

    def __init__(self, config: dict, data_store=None, evolution=None):
        super().__init__("Coordinator", config)
        self.config = config
        self.fetcher = FetcherAgent(config)
        self.parser = ParserAgent(config)
        self.analyzer = AnalyzerAgent(config, data_store)
        self.visualizer = VisualizationAgent(config)
        self.store = data_store
        self.evolution = evolution

    # ── sync (wraps async) ──────────────────────────────────────────

    def run(self, url: str, site_name: str = "default", use_browser: bool = False) -> dict:
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
        self, url: str, site_name: str = "default", use_browser: bool = False,
        profile: SiteProfile = None,
    ) -> dict:
        profile = profile or get_profile(site_name)
        start_time = time.time()
        result = {
            "site_name": site_name,
            "url": url,
            "status": "unknown",
            "error": None,
            "report": None,
            "charts": None,
        }

        try:
            # Step 1: Fetch
            fetch_result = await self.fetcher.run_async(url, use_browser=use_browser)
            content_hash = fetch_result["content_hash"]

            # Step 2: Check if content changed
            last_hash = self.store.get_last_hash(site_name) if self.store else None
            if last_hash == content_hash and last_hash is not None:
                logger.info(
                    "[Coordinator] No content change for %s, skipping.", site_name
                )
                result["status"] = "skipped_no_change"
                result["report"] = {
                    "site_name": site_name,
                    "content_hash": content_hash,
                    "has_changes": False,
                    "is_first_run": False,
                }
                if self.store:
                    elapsed = (time.time() - start_time) * 1000
                    self.store.log_run(site_name, "skipped_no_change", processing_time_ms=elapsed)
                return result

            # Step 3: Parse (with site profile)
            parse_result = self.parser.run(
                fetch_result["html"], site_name, page_url=url, profile=profile
            )
            items = parse_result["items"]
            confidence = parse_result["extraction_confidence"]

            # Step 4: Analyze
            report = await self.analyzer.run_async(items, site_name, content_hash)

            # Step 5: Save snapshot
            if self.store:
                self.store.save_snapshot(site_name, url, content_hash, items)

            # Step 6: Get snapshots for trends
            snapshots = self.store.get_all_snapshots(site_name) if self.store else []

            # Step 7: Visualize (run in thread — matplotlib is sync)
            chart_result = await asyncio.to_thread(
                self.visualizer.run, report, snapshots
            )

            # Step 8: Record evolution
            if self.evolution:
                self.evolution.record_run(
                    site_name, report, confidence, (time.time() - start_time) * 1000
                )

            result["status"] = "success"
            result["report"] = report
            result["charts"] = chart_result

            if self.store:
                elapsed = (time.time() - start_time) * 1000
                self.store.log_run(
                    site_name,
                    "success",
                    items_found=len(items),
                    changes_detected=report.get("total_changes", 0),
                    extraction_confidence=confidence,
                    processing_time_ms=elapsed,
                )

        except Exception as e:
            import traceback

            logger.error("[Coordinator] Pipeline failed for %s: %s", site_name, e)
            logger.error("[Coordinator] Traceback:\n%s", traceback.format_exc())
            result["status"] = "error"
            result["error"] = str(e)

            if self.store:
                elapsed = (time.time() - start_time) * 1000
                self.store.log_run(
                    site_name, "error", error_message=str(e), processing_time_ms=elapsed
                )

        return result

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
