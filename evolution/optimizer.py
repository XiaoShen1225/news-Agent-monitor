"""Evolution optimizer: tunes prompts and schedules based on run history."""

import logging
import tempfile
import os
from pathlib import Path
import yaml

from .memory import EvolutionMemory

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/extraction.yaml")


class EvolutionOptimizer:
    """Analyzes run history to optimize extraction prompts and poll intervals."""

    def __init__(self, config: dict, memory: EvolutionMemory):
        self.config = config
        self.memory = memory
        evo_config = config.get("evolution", {})
        self.enabled = evo_config.get("enabled", True)
        self.min_runs = evo_config.get("min_runs_before_optimize", 5)
        self.prompt_tuning = evo_config.get("prompt_tuning", True)
        self.schedule_tuning = evo_config.get("schedule_tuning", True)

    def run(self, site_name: str) -> dict:
        """Run evolution pass: analyze history, suggest/apply optimizations."""
        if not self.enabled:
            return {"status": "disabled"}

        stats = self.memory.get_stats(site_name)
        if stats.get("runs", 0) < self.min_runs:
            return {"status": "insufficient_data", "runs": stats.get("runs", 0)}

        optimizations = {}

        if self.prompt_tuning:
            prompt_result = self._optimize_prompt(site_name, stats)
            if prompt_result:
                optimizations["prompt"] = prompt_result

        if self.schedule_tuning:
            schedule_result = self._optimize_schedule(site_name, stats)
            if schedule_result:
                optimizations["schedule"] = schedule_result

        logger.info(
            "[Evolution] Optimization pass for %s: %s", site_name, optimizations
        )
        return {"status": "completed", "optimizations": optimizations, "stats": stats}

    def record_run(
        self,
        site_name: str,
        report: dict,
        confidence: float,
        elapsed_ms: float,
        total_tokens: int = 0,
    ):
        """Record a single run and trigger optimization if ready."""
        self.memory.add_record(site_name, report, confidence, elapsed_ms, total_tokens)
        return self.run(site_name)

    def _optimize_prompt(self, site_name: str, stats: dict) -> dict:
        """Tune extraction prompts if confidence is consistently low."""
        avg_confidence = stats.get("avg_confidence", 1.0)
        if avg_confidence >= 0.75:
            return None

        if not PROMPT_PATH.exists():
            return None

        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f) or {}

        site_prompts = prompts.get(site_name, prompts.get("default", {}))
        system = site_prompts.get("system", "")

        # Add more specific instructions to improve extraction quality
        improvements = []
        if avg_confidence < 0.5:
            improvements.append(
                "CRITICAL: Return ONLY valid JSON array. No markdown, no extra text."
            )

        if stats.get("runs", 0) > 3 and avg_confidence < 0.7:
            improvements.append("If unsure about a field, use null.")

        if improvements:
            enhanced = system + "\n" + "\n".join(improvements)
            prompts.setdefault(site_name, {})
            prompts[site_name]["system"] = enhanced

            tmp_fd, tmp_path = tempfile.mkstemp(
                suffix=".yaml", dir=PROMPT_PATH.parent, text=True
            )
            try:
                with open(tmp_fd, "w", encoding="utf-8") as f:
                    yaml.dump(prompts, f, allow_unicode=True, default_flow_style=False)
                os.replace(tmp_path, PROMPT_PATH)
            except Exception:
                os.unlink(tmp_path)
                raise

            logger.info("[Evolution] Enhanced extraction prompt for %s", site_name)
            return {"action": "enhanced_prompt", "improvements": improvements}

        return None

    def _optimize_schedule(self, site_name: str, stats: dict) -> dict:
        """Adjust poll interval based on change frequency and token cost.

        Persists optimized intervals to EvolutionMemory so they survive restarts.
        Verifies previous adjustments and rolls back ineffective changes.
        """
        change_freq = stats.get("change_frequency", 0.5)
        runs = stats.get("runs", 0)
        avg_tokens = stats.get("avg_tokens", 0)
        avg_changes = max(stats.get("avg_changes_per_run", 0), 1)
        tokens_per_change = avg_tokens / avg_changes

        targets = self.config.get("targets", [])
        for target in targets:
            if target.get("name") == site_name:
                current_interval = target.get("interval_minutes", 60)

                # ── Rollback verification ──────────────────────────
                last_adj = self.memory.get_last_adjustment(site_name)
                if last_adj:
                    runs_since = runs - last_adj.get("runs_at_time", 0)
                    if runs_since >= 3:
                        should_rollback = False
                        reason = ""

                        if last_adj["action"] in (
                            "increased_frequency",
                            "decreased_frequency",
                            "cost_throttled",
                        ):
                            if last_adj["action"] == "increased_frequency":
                                # Expect change_frequency to have improved by ≥0.1
                                improvement = (
                                    change_freq - last_adj["change_freq_before"]
                                )
                                if improvement < 0.1:
                                    should_rollback = True
                                    reason = (
                                        f"increased freq didn't improve change rate "
                                        f"(was {last_adj['change_freq_before']:.2f}, "
                                        f"now {change_freq:.2f})"
                                    )
                            else:
                                # decreased/cost_throttled: rollback if
                                # change_frequency dropped >0.2 (missed content)
                                drop = last_adj["change_freq_before"] - change_freq
                                if drop > 0.2:
                                    should_rollback = True
                                    reason = (
                                        f"reduced freq missed content "
                                        f"(was {last_adj['change_freq_before']:.2f}, "
                                        f"now {change_freq:.2f})"
                                    )

                        if should_rollback:
                            target["interval_minutes"] = last_adj["old_interval"]
                            self.memory.set_optimized_interval(
                                site_name, last_adj["old_interval"]
                            )
                            self.memory.clear_adjustment(site_name)
                            logger.warning(
                                "[Evolution] Rollback interval for %s: %d→%d min — %s",
                                site_name,
                                current_interval,
                                last_adj["old_interval"],
                                reason,
                            )
                            return {
                                "action": "rollback",
                                "old_interval": last_adj["new_interval"],
                                "new_interval": last_adj["old_interval"],
                                "reason": reason,
                            }

                # Cost-aware throttling: expensive but low-yield → slow down
                if (
                    tokens_per_change > 2000
                    and change_freq < 0.3
                    and current_interval < 120
                ):
                    new_interval = min(240, current_interval * 2)
                    target["interval_minutes"] = new_interval
                    self.memory.set_optimized_interval(site_name, new_interval)
                    self.memory.record_adjustment(
                        site_name,
                        current_interval,
                        new_interval,
                        "cost_throttled",
                        change_freq,
                        runs,
                    )
                    logger.info(
                        "[Evolution] Cost-throttled %s: %d→%d min "
                        "(%.0f tokens/change, change_freq=%.2f)",
                        site_name,
                        current_interval,
                        new_interval,
                        tokens_per_change,
                        change_freq,
                    )
                    return {
                        "action": "cost_throttled",
                        "old_interval": current_interval,
                        "new_interval": new_interval,
                        "tokens_per_change": tokens_per_change,
                    }

                if change_freq > 0.7 and current_interval > 30:
                    new_interval = max(15, current_interval // 2)
                    target["interval_minutes"] = new_interval
                    self.memory.set_optimized_interval(site_name, new_interval)
                    self.memory.record_adjustment(
                        site_name,
                        current_interval,
                        new_interval,
                        "increased_frequency",
                        change_freq,
                        runs,
                    )
                    logger.info(
                        "[Evolution] Increased poll frequency for %s: %d→%d min",
                        site_name,
                        current_interval,
                        new_interval,
                    )
                    return {
                        "action": "increased_frequency",
                        "old_interval": current_interval,
                        "new_interval": new_interval,
                    }

                if change_freq < 0.2 and current_interval < 120:
                    new_interval = min(240, current_interval * 2)
                    target["interval_minutes"] = new_interval
                    self.memory.set_optimized_interval(site_name, new_interval)
                    self.memory.record_adjustment(
                        site_name,
                        current_interval,
                        new_interval,
                        "decreased_frequency",
                        change_freq,
                        runs,
                    )
                    logger.info(
                        "[Evolution] Decreased poll frequency for %s: %d→%d min",
                        site_name,
                        current_interval,
                        new_interval,
                    )
                    return {
                        "action": "decreased_frequency",
                        "old_interval": current_interval,
                        "new_interval": new_interval,
                    }

                break

        return None
