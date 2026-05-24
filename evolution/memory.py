"""Evolution memory: records run metrics for self-improvement."""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

MEMORY_FILE = "data/evolution_memory.json"
INTERVALS_FILE = "data/evolution_intervals.json"
ADJUSTMENTS_FILE = "data/evolution_adjustments.json"


class EvolutionMemory:
    def __init__(self, filepath: str = MEMORY_FILE):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.records = self._load()
        self._intervals_path = self.filepath.parent / Path(INTERVALS_FILE).name
        self._intervals: dict[str, int] = self._load_intervals()
        self._adjustments_path = self.filepath.parent / Path(ADJUSTMENTS_FILE).name
        self._adjustments: dict[str, dict] = self._load_adjustments()

    def _load(self) -> list:
        if self.filepath.exists():
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self):
        tmp_path = self.filepath.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.records, f, ensure_ascii=False, indent=2)
        tmp_path.replace(self.filepath)

    def _load_intervals(self) -> dict[str, int]:
        if self._intervals_path.exists():
            with open(self._intervals_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_intervals(self):
        tmp_path = self._intervals_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._intervals, f, ensure_ascii=False, indent=2)
        tmp_path.replace(self._intervals_path)

    def set_optimized_interval(self, site_name: str, interval: int):
        self._intervals[site_name] = interval
        self._save_intervals()
        logger.info(
            "[Evolution] Persisted optimized interval for %s: %d min",
            site_name,
            interval,
        )

    def get_optimized_interval(self, site_name: str) -> int | None:
        return self._intervals.get(site_name)

    # ── adjustment history (for rollback verification) ────────────────

    def _load_adjustments(self) -> dict[str, dict]:
        if self._adjustments_path.exists():
            with open(self._adjustments_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_adjustments(self):
        tmp_path = self._adjustments_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._adjustments, f, ensure_ascii=False, indent=2)
        tmp_path.replace(self._adjustments_path)

    def record_adjustment(
        self,
        site_name: str,
        old_interval: int,
        new_interval: int,
        action: str,
        change_freq_before: float,
        runs_at_time: int,
    ):
        self._adjustments[site_name] = {
            "timestamp": datetime.now().isoformat(),
            "old_interval": old_interval,
            "new_interval": new_interval,
            "action": action,
            "change_freq_before": change_freq_before,
            "runs_at_time": runs_at_time,
        }
        self._save_adjustments()
        logger.info(
            "[Evolution] Recorded adjustment for %s: %s %d→%d min",
            site_name,
            action,
            old_interval,
            new_interval,
        )

    def get_last_adjustment(self, site_name: str) -> dict | None:
        return self._adjustments.get(site_name)

    def clear_adjustment(self, site_name: str):
        self._adjustments.pop(site_name, None)
        self._save_adjustments()

    def add_record(
        self,
        site_name: str,
        report: dict,
        confidence: float,
        elapsed_ms: float,
        total_tokens: int = 0,
    ):
        record = {
            "timestamp": datetime.now().isoformat(),
            "site_name": site_name,
            "items_count": report.get("current_count", 0),
            "changes_detected": report.get("total_changes", 0),
            "extraction_confidence": confidence,
            "processing_time_ms": round(elapsed_ms, 1),
            "has_changes": report.get("has_changes", False),
            "tag_distribution": report.get("tag_distribution", {}),
            "total_tokens": total_tokens,
        }
        self.records.append(record)
        self._save()
        logger.info("[Evolution] Recorded run #%d for %s", len(self.records), site_name)

    def get_recent(self, site_name: str, n: int = 10) -> list:
        site_records = [r for r in self.records if r["site_name"] == site_name]
        return site_records[-n:]

    def get_stats(self, site_name: str) -> dict:
        site_records = [r for r in self.records if r["site_name"] == site_name]
        if not site_records:
            return {"runs": 0}

        confidences = [r["extraction_confidence"] for r in site_records]
        times = [r["processing_time_ms"] for r in site_records]
        change_rates = [r["changes_detected"] for r in site_records]

        tokens = [r.get("total_tokens", 0) for r in site_records]

        return {
            "runs": len(site_records),
            "avg_confidence": round(sum(confidences) / len(confidences), 3),
            "avg_time_ms": round(sum(times) / len(times), 0),
            "avg_changes_per_run": round(sum(change_rates) / len(change_rates), 1),
            "change_frequency": round(
                sum(1 for r in site_records if r["has_changes"]) / len(site_records), 2
            ),
            "avg_tokens": round(sum(tokens) / len(tokens), 0),
        }
