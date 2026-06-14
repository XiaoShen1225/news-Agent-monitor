"""CoordinatorAgent: orchestrates the full multi-agent pipeline — sync + async."""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime

from .base_agent import BaseAgent
from .fetcher import FetcherAgent
from .parser import ParserAgent
from .analyzer import AnalyzerAgent
from .sentiment_analyzer import classify
from .site_profiles import SiteProfile, get_profile
from data.watch_store import WatchStore
from notifications.dispatcher import build_event, notify_all
from web.middleware.logging import trace_ctx

logger = logging.getLogger(__name__)


class CoordinatorAgent(BaseAgent):
    """Orchestrates Fetcher → Parser → Analyzer → Visualizer pipeline."""

    def __init__(
        self,
        config: dict,
        data_store=None,
        paper_store=None,
        notifiers=None,
        vector_store=None,
    ):
        super().__init__("Coordinator", config)
        self.config = config
        self.fetcher = FetcherAgent(config)
        self.parser = ParserAgent(config)
        self.analyzer = AnalyzerAgent(config, data_store)
        self.store = data_store
        self.paper_store = paper_store or data_store
        self.notifiers = notifiers or []
        self._vector_store = vector_store
        self.watch_store = WatchStore()
        self.watch_store.load_config(config)
        self.max_snapshots = config.get("storage", {}).get("max_snapshots_per_site", 0)
        self._run_callbacks: list = []

    @property
    def vector_store(self):
        return self._vector_store

    @vector_store.setter
    def vector_store(self, value):
        self._vector_store = value

    def add_run_callback(self, callback):
        """Register an async callback invoked after each run_async completes."""
        self._run_callbacks.append(callback)

    # ── preference / watch context builders ───────────────────────────

    def _build_watch_context(self, items: list) -> dict:
        """Build watch-context dict for personalized analyzer summaries."""
        active = self.watch_store.list_watches(status="active")
        topics = []
        matched_items = []
        seen = set()
        for w in active:
            kws = w.get("keywords", [])
            title = w.get("title", "")
            if kws or title:
                topics.append({"title": title, "keywords": kws})
            for item in items:
                item_title = item.get("title", "")
                for kw in kws:
                    if kw and kw in item_title:
                        key = (w["id"], item_title[:40])
                        if key not in seen:
                            seen.add(key)
                            matched_items.append(
                                {
                                    "watch_title": title,
                                    "item_title": item_title[:80],
                                    "keyword": kw,
                                }
                            )
                        break
        return {"active_topics": topics, "matched_items": matched_items}

    @staticmethod
    def _build_preference_context() -> str:
        """Read L1/L2 preference data for prompt injection (read-only from disk)."""
        try:
            from agents.preference_engine import PreferenceEngine
            from web.app_context import ctx

            # Reuse the shared engine if available (properly wired with track_store)
            if (
                ctx.chat_agent is not None
                and ctx.chat_agent._preference_engine is not None
            ):
                return ctx.chat_agent._preference_engine.format_for_prompt()

            # Fallback: read-only instance (format_for_prompt only reads disk files)
            engine = PreferenceEngine(track_store=ctx.track_store)
            return engine.format_for_prompt()
        except Exception:
            return ""

    # ── sync (wraps async) ──────────────────────────────────────────

    def run(
        self, url: str, site_name: str = "default", use_browser: bool = False
    ) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(url, site_name, use_browser))
        raise RuntimeError("Coordinator.run() in async context — use run_async()")

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
        trace_ctx.set(trace_id=trace_id)
        start_time = time.time()
        result = {
            "site_name": site_name,
            "url": url,
            "status": "unknown",
            "error": None,
            "report": None,
        }

        # Circuit breaker: skip sites that have failed too many times in a row.
        # Falls through to callbacks so the dashboard is still notified of the skip.
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
        else:
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
                fetch_result = await self.fetcher.run_async(
                    url, use_browser=use_browser
                )
                content_hash = fetch_result["content_hash"]

                # Step 2: Check if content changed
                last_hash = (
                    active_store.get_last_hash(site_name) if active_store else None
                )
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
                        "timestamp": datetime.now().isoformat(),
                    }
                    if active_store:
                        active_store.reset_failure(site_name)
                        active_store.log_run(
                            site_name,
                            "skipped_no_change",
                            processing_time_ms=elapsed,
                            trace_id=trace_id,
                        )
                    # No notify_all for no-change, but callbacks fire below
                else:
                    # Step 3: Parse (with site profile)
                    parse_result = await self.parser.run_async(
                        fetch_result["html"],
                        site_name,
                        url,
                        profile,
                    )
                    items = parse_result["items"]
                    confidence = parse_result["extraction_confidence"]

                    # Step 3b: Sentiment labeling (rule-based, no LLM cost)
                    for item in items:
                        if not item.get("sentiment"):
                            item["sentiment"] = classify(item.get("title", ""))

                    # Step 4: Analyze (with personalized context)
                    watch_ctx = self._build_watch_context(items)
                    pref_ctx = self._build_preference_context()
                    report = await self.analyzer.run_async(
                        items,
                        site_name,
                        content_hash,
                        store=active_store,
                        watch_context=watch_ctx,
                        preference_context=pref_ctx,
                    )

                    # Step 5: Save snapshot
                    if active_store:
                        active_store.save_snapshot(site_name, url, content_hash, items)
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
                        if self.max_snapshots > 0:
                            active_store.prune_snapshots(site_name, self.max_snapshots)
                        if self.vector_store:
                            try:
                                self.vector_store.add_items(items, site_name)
                            except Exception as e:
                                logger.warning("Vector store indexing failed: %s", e)

                    result["status"] = "success"
                    result["report"] = report

                    # ── Watch matching (unified topic + event) ────────
                    new_items = report.get("new_items", [])
                    watch_matches = {
                        "keyword_matches": [],
                        "semantic_matches": [],
                    }
                    if new_items:
                        try:
                            watch_matches = self.watch_store.check_new_items(
                                new_items, self.vector_store
                            )
                        except Exception as e:
                            logger.warning("[Coordinator] Watch matching failed: %s", e)
                    result["watch_matches"] = watch_matches

                    # Anomaly detection cooldown check
                    alert_config = self.config.get("alerts", {}) or {}
                    anomalies = report.get("anomalies", [])
                    result["anomalies"] = []
                    anomaly_cfg = alert_config.get("anomaly", {})
                    cooldown_min = anomaly_cfg.get("cooldown_minutes", 120)
                    for a in anomalies:
                        if self.watch_store.should_alert_anomaly(
                            site_name, a["type"], cooldown_min
                        ):
                            result["anomalies"].append(a)
                            self.watch_store.log_anomaly_alert(
                                site_name,
                                a["type"],
                                f"{a['type']}: current={a['current_count']},"
                                f" baseline={a['baseline_avg']}",
                            )

                    # Sentiment shift check
                    sentiment_shift = report.get("sentiment_shift", {}) or {}
                    if sentiment_shift.get("significant"):
                        result["sentiment_shift"] = sentiment_shift
                        self.watch_store.log_sentiment_shift(
                            site_name,
                            f"情感偏移: {sentiment_shift.get('shifted', {})}",
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

                    notify_cfg = (self.config.get("notifications") or {}).get(
                        "policy"
                    ) or {}
                    await notify_all(
                        self.notifiers,
                        build_event(result),
                        quiet_start=notify_cfg.get("quiet_start", ""),
                        quiet_end=notify_cfg.get("quiet_end", ""),
                        cooldown_minutes=notify_cfg.get("dedup_cooldown_minutes", 120),
                    )

            except Exception as e:
                import traceback

                elapsed = (time.time() - start_time) * 1000
                # Walk __cause__ chain for meaningful message (e.g. httpx.ConnectError has empty str())
                error_str = str(e).strip()
                cause = getattr(e, "__cause__", None)
                seen_ids = set()
                while not error_str and cause is not None and id(cause) not in seen_ids:
                    seen_ids.add(id(cause))
                    error_str = str(cause).strip()
                    cause = getattr(cause, "__cause__", None)
                if not error_str:
                    error_str = repr(e)
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
                            "[Coordinator] Circuit breaker OPEN for %s"
                            " — will skip for 1 hour",
                            site_name,
                        )
                    active_store.log_run(
                        site_name,
                        "error",
                        error_message=str(e),
                        processing_time_ms=elapsed,
                        trace_id=trace_id,
                    )

                notify_cfg = (self.config.get("notifications") or {}).get(
                    "policy"
                ) or {}
                await notify_all(
                    self.notifiers,
                    build_event(result),
                    quiet_start=notify_cfg.get("quiet_start", ""),
                    quiet_end=notify_cfg.get("quiet_end", ""),
                    cooldown_minutes=notify_cfg.get("dedup_cooldown_minutes", 120),
                )

        # ── Unified exit: callbacks fire for ALL statuses ─────────
        for cb in self._run_callbacks:
            try:
                await cb(result)
            except Exception:
                logger.warning(
                    "[Coordinator] run_callback failed:\n%s",
                    traceback.format_exc(),
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
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
