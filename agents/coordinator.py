"""CoordinatorAgent: orchestrates the full multi-agent pipeline."""

import time
import logging

from .base_agent import BaseAgent
from .fetcher import FetcherAgent
from .parser import ParserAgent
from .analyzer import AnalyzerAgent
from .visualizer import VisualizationAgent

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

    def run(self, url: str, site_name: str = "default", use_browser: bool = False) -> dict:
        """Execute the full pipeline for a single URL."""
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
            fetch_result = self.fetcher.run(url, use_browser=use_browser)
            content_hash = fetch_result["content_hash"]

            # Step 2: Check if content changed
            last_hash = self.store.get_last_hash(site_name) if self.store else None
            if last_hash == content_hash and last_hash is not None:
                logger.info("[Coordinator] No content change for %s, skipping parse+analyze.", site_name)
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

            # Step 3: Parse (structural extraction)
            parse_result = self.parser.run(fetch_result["html"], site_name, page_url=url)
            items = parse_result["items"]
            confidence = parse_result["extraction_confidence"]

            # Step 4: Analyze (compare with history BEFORE saving current snapshot)
            report = self.analyzer.run(items, site_name, content_hash)

            # Step 5: Save snapshot (AFTER analysis so diff works correctly)
            if self.store:
                self.store.save_snapshot(site_name, url, content_hash, items)

            # Step 6: Get all snapshots for trend visualization
            snapshots = self.store.get_all_snapshots(site_name) if self.store else []

            # Step 7: Visualize
            chart_result = self.visualizer.run(report, snapshots)

            # Step 8: Record evolution metrics
            if self.evolution:
                self.evolution.record_run(site_name, report, confidence,
                                          (time.time() - start_time) * 1000)

            result["status"] = "success"
            result["report"] = report
            result["charts"] = chart_result

            if self.store:
                elapsed = (time.time() - start_time) * 1000
                self.store.log_run(
                    site_name, "success",
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
                self.store.log_run(site_name, "error", error_message=str(e),
                                   processing_time_ms=elapsed)

        return result

    def run_all_targets(self) -> list:
        """Run pipeline for all configured targets."""
        targets = self.config.get("targets", [])
        results = []
        for target in targets:
            result = self.run(target["url"], target["name"],
                              use_browser=target.get("use_browser", False))
            results.append(result)
        return results
