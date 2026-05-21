"""Evolution memory: records run metrics for self-improvement."""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

MEMORY_FILE = "data/evolution_memory.json"


class EvolutionMemory:
    def __init__(self, filepath: str = MEMORY_FILE):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.records = self._load()

    def _load(self) -> list:
        if self.filepath.exists():
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.records, f, ensure_ascii=False, indent=2)

    def add_record(self, site_name: str, report: dict, confidence: float, elapsed_ms: float):
        record = {
            "timestamp": datetime.now().isoformat(),
            "site_name": site_name,
            "items_count": report.get("current_count", 0),
            "changes_detected": report.get("total_changes", 0),
            "extraction_confidence": confidence,
            "processing_time_ms": round(elapsed_ms, 1),
            "has_changes": report.get("has_changes", False),
            "tag_distribution": report.get("tag_distribution", {}),
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

        return {
            "runs": len(site_records),
            "avg_confidence": round(sum(confidences) / len(confidences), 3),
            "avg_time_ms": round(sum(times) / len(times), 0),
            "avg_changes_per_run": round(sum(change_rates) / len(change_rates), 1),
            "change_frequency": round(
                sum(1 for r in site_records if r["has_changes"]) / len(site_records), 2
            ),
        }
