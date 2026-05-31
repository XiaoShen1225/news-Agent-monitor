"""Unified alert storage shared by ChatAgent and the Coordinator pipeline."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class AlertStore:
    """Manages keyword alerts, alert dedup log, and cooldown rules.

    Storage: single JSON file at ``data/alerts.json``.
    Shared between ChatAgent (set_alert tool) and Coordinator (pipeline keyword matching).
    """

    def __init__(self, file_path: str = "data/alerts.json"):
        self._path = Path(file_path)
        self._data = self._load()

    # ── file I/O ────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("AlertStore: corrupt file, starting fresh")
        return {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── keyword CRUD ────────────────────────────────────────────────────

    def get_keywords(self) -> list[dict]:
        """Return all alert keywords: [{"keyword": "华为", "created_at": "..."}, ...]."""
        return self._data.get("keywords", [])

    def add_keyword(self, keyword: str) -> dict:
        """Add a keyword. Returns status dict for ChatAgent response."""
        keywords = self._data.setdefault("keywords", [])
        kw = keyword.strip()
        if not kw:
            return {"ok": False, "msg": "keyword 参数不能为空"}
        if any(k["keyword"] == kw for k in keywords):
            return {"ok": True, "msg": f"关键词「{kw}」已在告警列表中"}
        keywords.append({"keyword": kw, "created_at": _now_iso()})
        self._save()
        return {"ok": True, "msg": f"已添加关键词「{kw}」"}

    def remove_keyword(self, keyword: str) -> dict:
        keywords = self._data.get("keywords", [])
        before = len(keywords)
        self._data["keywords"] = [
            k for k in keywords if k["keyword"] != keyword.strip()
        ]
        if len(self._data["keywords"]) < before:
            self._save()
            return {"ok": True, "msg": f"已移除关键词「{keyword}」"}
        return {"ok": False, "msg": f"未找到关键词「{keyword}」"}

    # ── pipeline keyword matching ───────────────────────────────────────

    def match_items(self, items: list[dict]) -> list[dict]:
        """Check new items against all alert keywords.

        Returns list of matches: [{"keyword": ..., "title": ..., "url": ..., "tag": ...}].
        Only returns matches that pass the cooldown check (no duplicate within 24h).
        """
        keywords = self.get_keywords()
        if not keywords or not items:
            return []

        matches = []
        cooldown_hours = self._data.get("config", {}).get("keyword_cooldown_hours", 24)

        for item in items:
            title = item.get("title", "")
            for kw_entry in keywords:
                kw = kw_entry["keyword"]
                if kw in title:
                    if self._should_alert_keyword(kw, cooldown_hours):
                        matches.append(
                            {
                                "keyword": kw,
                                "title": title[:80],
                                "url": item.get("url", ""),
                                "tag": item.get("tag", ""),
                            }
                        )
                        self._log_keyword_hit(kw, title)

        return matches

    # ── cooldown / dedup ─────────────────────────────────────────────────

    def _should_alert_keyword(self, keyword: str, cooldown_hours: int) -> bool:
        """Check whether this keyword was already alerted within the cooldown window."""
        log = self._data.get("alert_log", [])
        cutoff = datetime.now() - timedelta(hours=cooldown_hours)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
        for entry in reversed(log):
            if entry.get("type") != "keyword":
                continue
            if entry.get("keyword") == keyword and entry.get("time", "") > cutoff_str:
                return False
        return True

    def should_alert_anomaly(
        self, site_name: str, anomaly_type: str, cooldown_minutes: int = 120
    ) -> bool:
        """Check whether an anomaly alert should fire (cooldown gated)."""
        log = self._data.get("alert_log", [])
        cutoff = datetime.now() - timedelta(minutes=cooldown_minutes)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
        for entry in reversed(log):
            if entry.get("type") != "anomaly":
                continue
            if (
                entry.get("site") == site_name
                and entry.get("anomaly_type") == anomaly_type
                and entry.get("time", "") > cutoff_str
            ):
                return False
        return True

    def _log_keyword_hit(self, keyword: str, title: str):
        self._data.setdefault("alert_log", []).append(
            {
                "type": "keyword",
                "keyword": keyword,
                "title": title[:100],
                "time": _now_iso(),
            }
        )
        self._save()

    def log_anomaly_alert(self, site_name: str, anomaly_type: str, message: str):
        self._data.setdefault("alert_log", []).append(
            {
                "type": "anomaly",
                "site": site_name,
                "anomaly_type": anomaly_type,
                "message": message,
                "time": _now_iso(),
            }
        )
        self._save()

    def log_sentiment_shift(self, site_name: str, message: str):
        self._data.setdefault("alert_log", []).append(
            {
                "type": "sentiment_shift",
                "site": site_name,
                "message": message,
                "time": _now_iso(),
            }
        )
        self._save()

    # ── config ───────────────────────────────────────────────────────────

    def load_config(self, config: dict):
        """Sync alert config from config.yaml's 'alerts' section."""
        cfg = config.get("alerts", {}) or {}
        anomaly_cfg = cfg.get("anomaly", {})
        keyword_cfg = cfg.get("keyword", {})
        self._data["config"] = {
            "anomaly_enabled": anomaly_cfg.get("enabled", True),
            "anomaly_zscore": anomaly_cfg.get("zscore_threshold", 2.5),
            "anomaly_baseline": anomaly_cfg.get("baseline_snapshots", 10),
            "anomaly_cooldown_minutes": anomaly_cfg.get("cooldown_minutes", 120),
            "sentiment_enabled": cfg.get("sentiment", {}).get("enabled", True),
            "sentiment_shift_threshold": cfg.get("sentiment", {}).get(
                "shift_threshold", 0.3
            ),
            "keyword_cooldown_hours": keyword_cfg.get("cooldown_hours", 24),
        }
        self._save()

    def get_config(self) -> dict:
        return self._data.get("config", {})


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
