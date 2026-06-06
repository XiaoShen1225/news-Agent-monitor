"""Unified WatchStore: topic monitoring + event tracking.

Single JSON file at ``data/watches.json``.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class WatchStore:
    """Unified watch store — topic monitoring + event tracking.

    Types
    -----
    - **topic**: keyword substring + semantic cosine dual matching.
      Long-term, user completes manually.  Keywords required.
    - **event**: semantic-only matching.
      Finite lifecycle — active until user completes.

    Lifecycle
    ---------
    ``active`` → ``completed`` (user), ``paused`` (user), or
    stale-prompt (broadcast after N days without match, configurable).
    """

    def __init__(self, file_path: str = "data/watches.json"):
        self._path = Path(file_path)
        self._data = self._load()

    # ── file I/O ────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("WatchStore: corrupt file, starting fresh")
        return {"watches": [], "config": {}}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── CRUD ────────────────────────────────────────────────────────

    def add_watch(
        self,
        watch_type: str,
        title: str,
        keywords: list = None,
        embedding: list = None,
        source_site: str = "",
    ) -> dict:
        """Add a watch. Returns status dict."""
        title = title.strip()
        if not title:
            return {"ok": False, "msg": "标题不能为空"}

        if watch_type not in ("topic", "event"):
            watch_type = "topic"

        # Dedup by exact title
        for w in self._data.get("watches", []):
            if w["title"] == title:
                return {
                    "ok": True,
                    "msg": f"已在关注列表中（类型: {w['type']}, 状态: {w['status']}）",
                    "watch_id": w["id"],
                }

        watch_id = f"watch_{uuid.uuid4().hex[:10]}"
        watch = {
            "id": watch_id,
            "type": watch_type,
            "title": title,
            "keywords": keywords or [],
            "embedding": embedding or [],
            "status": "active",
            "match_strategy": (
                "semantic_only" if watch_type == "event" else "keyword_and_semantic"
            ),
            "created_at": _now_iso(),
            "last_match_at": None,
            "match_count": 0,
            "match_history": [],
            "latest_summary": None,
            "source_site": source_site,
            "completed_at": None,
        }
        self._data.setdefault("watches", []).append(watch)
        self._save()
        kind = "主题" if watch_type == "topic" else "事件"
        logger.info("[WatchStore] Added %s watch: %s", watch_type, title[:60])
        return {
            "ok": True,
            "msg": f"已开始追踪{kind}「{title[:40]}」",
            "watch_id": watch_id,
        }

    def remove_watch(self, watch_id: str) -> dict:
        watches = self._data.get("watches", [])
        before = len(watches)
        self._data["watches"] = [w for w in watches if w["id"] != watch_id]
        if len(self._data["watches"]) < before:
            self._save()
            return {"ok": True, "msg": "已移除关注"}
        return {"ok": False, "msg": "未找到该关注项"}

    def complete_watch(self, watch_id: str) -> dict:
        for w in self._data.get("watches", []):
            if w["id"] == watch_id:
                w["status"] = "completed"
                w["completed_at"] = _now_iso()
                self._save()
                return {"ok": True, "msg": f"「{w['title'][:40]}」已标记为完成"}
        return {"ok": False, "msg": "未找到该关注项"}

    def pause_watch(self, watch_id: str) -> dict:
        for w in self._data.get("watches", []):
            if w["id"] == watch_id:
                w["status"] = "paused"
                self._save()
                return {"ok": True, "msg": f"「{w['title'][:40]}」已暂停"}
        return {"ok": False, "msg": "未找到该关注项"}

    def resume_watch(self, watch_id: str) -> dict:
        for w in self._data.get("watches", []):
            if w["id"] == watch_id:
                w["status"] = "active"
                self._save()
                return {"ok": True, "msg": f"「{w['title'][:40]}」已恢复追踪"}
        return {"ok": False, "msg": "未找到该关注项"}

    def list_watches(
        self, watch_type: str = None, status: str = None, include_matches: bool = False
    ) -> list[dict]:
        watches = self._data.get("watches", [])
        result = []
        for w in watches:
            if watch_type and w.get("type") != watch_type:
                continue
            if status and w.get("status") != status:
                continue
            entry = {
                "id": w["id"],
                "type": w.get("type", "topic"),
                "title": w["title"],
                "keywords": w.get("keywords", []),
                "status": w.get("status", "active"),
                "match_strategy": w.get("match_strategy", ""),
                "match_count": w.get("match_count", 0),
                "created_at": w.get("created_at", ""),
                "last_match_at": w.get("last_match_at"),
                "source_site": w.get("source_site", ""),
                "latest_summary": w.get("latest_summary"),
            }
            if include_matches:
                entry["match_history"] = w.get("match_history", [])[-20:]
            result.append(entry)
        return result

    def get_watch(self, watch_id: str) -> dict | None:
        for w in self._data.get("watches", []):
            if w["id"] == watch_id:
                return w
        return None

    # ── retroactive initialization ───────────────────────────────────

    def initialize_matches(self, watch_id: str, items: list[dict], vector_store) -> int:
        """Search existing items for a newly created watch.

        Returns the number of initial matches found.
        """
        w = self.get_watch(watch_id)
        if not w:
            return 0
        if not items:
            return 0

        config = self._data.get("config", {})
        threshold = config.get("similarity_threshold", 0.7)

        found = 0
        titles = [it.get("title", "") for it in items]

        # Keyword matching for topic watches
        kws = w.get("keywords", [])
        if kws and w.get("type") == "topic":
            for item in items:
                title = item.get("title", "")
                for kw in kws:
                    if kw in title:
                        self._record_match(
                            w,
                            {
                                "watch_id": watch_id,
                                "watch_title": w["title"],
                                "item_title": title[:100],
                                "item_url": item.get("url", ""),
                                "match_type": "keyword",
                                "keyword": kw,
                                "site": item.get("site_name", ""),
                            },
                        )
                        found += 1
                        break

        # Semantic matching for watches with embeddings
        watch_emb = w.get("embedding", [])
        if watch_emb and vector_store:
            item_embs = self._get_embeddings(titles, vector_store)
            for i, item_emb in enumerate(item_embs):
                if not item_emb:
                    continue
                score = _cosine_sim(watch_emb, item_emb)
                if score >= threshold:
                    item = items[i]
                    if not _is_near_duplicate(item.get("title", ""), w["title"]):
                        self._record_match(
                            w,
                            {
                                "watch_id": watch_id,
                                "watch_title": w["title"],
                                "item_title": item.get("title", "")[:100],
                                "item_url": item.get("url", ""),
                                "match_type": "semantic",
                                "score": round(score, 3),
                                "site": item.get("site_name", ""),
                            },
                        )
                        found += 1

        if found:
            logger.info(
                "[WatchStore] Initialized %d matches for watch %s", found, watch_id
            )
        return found

    # ── matching ────────────────────────────────────────────────────

    def check_new_items(
        self,
        new_items: list[dict],
        vector_store,
        keyword_threshold: float = None,
        semantic_threshold: float = None,
    ) -> dict:
        """Check new items against all active watches.

        Topic watches: keyword substring first, then semantic for
        those with embeddings.  Event watches: semantic only.

        Returns dict with ``keyword_matches`` and ``semantic_matches`` lists.
        """
        watches = self._data.get("watches", [])
        active = [w for w in watches if w["status"] == "active"]
        if not active or not new_items:
            return {"keyword_matches": [], "semantic_matches": []}

        config = self._data.get("config", {})
        if semantic_threshold is None:
            semantic_threshold = config.get("similarity_threshold", 0.7)
        cooldown_hours = config.get("match_cooldown_hours", 12)

        now = datetime.now()
        keyword_matches = []
        semantic_matches = []

        # Separate topic / event watches
        topic_watches = [w for w in active if w.get("type") == "topic"]
        event_watches = [w for w in active if w.get("type") == "event"]

        # ── Topic: keyword matching (free, always run) ──
        for w in topic_watches:
            if self._in_cooldown(w, now, cooldown_hours):
                continue
            kws = w.get("keywords", [])
            if not kws:
                continue
            for item in new_items:
                title = item.get("title", "")
                for kw in kws:
                    if kw in title:
                        match = {
                            "watch_id": w["id"],
                            "watch_title": w["title"],
                            "item_title": title[:100],
                            "item_url": item.get("url", ""),
                            "match_type": "keyword",
                            "keyword": kw,
                            "site": item.get("site_name", ""),
                        }
                        keyword_matches.append(match)
                        self._record_match(w, match)
                        break  # one match per item per watch for keyword

        # ── Semantic: both topic (with embeddings) and event ──
        semantic_candidates = event_watches + [
            w for w in topic_watches if w.get("embedding")
        ]
        if semantic_candidates and vector_store:
            item_titles = [it.get("title", "") for it in new_items]
            item_embeddings = self._get_embeddings(item_titles, vector_store)

            for w in semantic_candidates:
                if self._in_cooldown(w, now, cooldown_hours):
                    continue
                watch_emb = w.get("embedding", [])
                if not watch_emb:
                    continue
                best_score = 0.0
                best_item = None
                for i, item_emb in enumerate(item_embeddings):
                    if not item_emb:
                        continue
                    score = _cosine_sim(watch_emb, item_emb)
                    if score >= semantic_threshold and score > best_score:
                        it_title = new_items[i].get("title", "")
                        if _is_near_duplicate(it_title, w["title"]):
                            continue
                        best_score = score
                        best_item = new_items[i]

                if best_item:
                    match = {
                        "watch_id": w["id"],
                        "watch_title": w["title"],
                        "item_title": best_item.get("title", "")[:100],
                        "item_url": best_item.get("url", ""),
                        "match_type": "semantic",
                        "score": round(best_score, 3),
                        "site": best_item.get("site_name", ""),
                    }
                    semantic_matches.append(match)
                    self._record_match(w, match)

        if keyword_matches or semantic_matches:
            logger.info(
                "[WatchStore] %d keyword + %d semantic matches",
                len(keyword_matches),
                len(semantic_matches),
            )
        return {
            "keyword_matches": keyword_matches,
            "semantic_matches": semantic_matches,
        }

    def _record_match(self, watch: dict, match: dict):
        now = _now_iso()
        watch["last_match_at"] = now
        watch["match_count"] = watch.get("match_count", 0) + 1
        history = watch.setdefault("match_history", [])
        history.append(
            {
                "time": now,
                "title": match["item_title"][:100],
                "url": match.get("item_url", ""),
                "score": match.get("score", 0),
                "match_type": match.get("match_type", "keyword"),
            }
        )
        if len(history) > 20:
            watch["match_history"] = history[-20:]
        # Invalidate cached summary so next fetch regenerates
        watch["latest_summary"] = None
        self._save()

    # ── cooldown ────────────────────────────────────────────────────

    def _in_cooldown(self, watch: dict, now: datetime, hours: int) -> bool:
        last = watch.get("last_match_at")
        if not last:
            return False
        try:
            last_dt = datetime.fromisoformat(last)
            return (now - last_dt) < timedelta(hours=hours)
        except ValueError:
            return False

    # ── stale detection ─────────────────────────────────────────────

    def get_stale_watches(self, days: int = None) -> list[dict]:
        """Return active watches with no match in N days (default from config)."""
        if days is None:
            days = self._data.get("config", {}).get("stale_prompt_days", 14)
        now = datetime.now()
        stale = []
        for w in self._data.get("watches", []):
            if w.get("status") != "active":
                continue
            last = w.get("last_match_at") or w.get("created_at", "")
            if not last:
                continue
            try:
                last_dt = datetime.fromisoformat(last)
                if (now - last_dt) > timedelta(days=days):
                    stale.append(
                        {
                            "id": w["id"],
                            "title": w["title"],
                            "type": w.get("type", "topic"),
                            "days_since_match": (now - last_dt).days,
                        }
                    )
            except ValueError:
                pass
        return stale

    # ── anomaly / sentiment ────────────────────────────────────────

    def should_alert_anomaly(
        self, site_name: str, anomaly_type: str, cooldown_minutes: int = 120
    ) -> bool:
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

    # ── summary cache ───────────────────────────────────────────────

    def set_latest_summary(self, watch_id: str, summary: str):
        for w in self._data.get("watches", []):
            if w["id"] == watch_id:
                w["latest_summary"] = summary
                self._save()
                return

    def get_latest_summary(self, watch_id: str) -> str | None:
        w = self.get_watch(watch_id)
        return w.get("latest_summary") if w else None

    # ── config ──────────────────────────────────────────────────────

    def load_config(self, config: dict):
        """Sync watch config from config.yaml 'watch' and 'alerts' sections."""
        watch_cfg = config.get("watch", {}) or {}
        alert_cfg = config.get("alerts", {}) or {}
        anomaly_cfg = alert_cfg.get("anomaly", {})
        sentiment_cfg = alert_cfg.get("sentiment", {})
        self._data["config"] = {
            "similarity_threshold": watch_cfg.get("similarity_threshold", 0.7),
            "match_cooldown_hours": watch_cfg.get("match_cooldown_hours", 12),
            "stale_prompt_days": watch_cfg.get("stale_prompt_days", 14),
            "anomaly_enabled": anomaly_cfg.get("enabled", True),
            "anomaly_zscore": anomaly_cfg.get("zscore_threshold", 2.5),
            "anomaly_cooldown_minutes": anomaly_cfg.get("cooldown_minutes", 120),
            "sentiment_enabled": sentiment_cfg.get("enabled", True),
            "sentiment_shift_threshold": sentiment_cfg.get("shift_threshold", 0.3),
        }
        self._save()

    def get_config(self) -> dict:
        return self._data.get("config", {})

    # ── embedding helper ────────────────────────────────────────────

    def compute_embedding(self, text: str, vector_store) -> list | None:
        try:
            ef = vector_store._ef
            result = ef([text])
            if result and result[0] is not None:
                return [float(v) for v in result[0]]
        except Exception as e:
            logger.warning("[WatchStore] Embedding failed: %s", e)
        return None

    @staticmethod
    def _get_embeddings(titles: list[str], vector_store) -> list:
        try:
            ef = vector_store._ef
            embeddings = ef(titles)
            return [list(e) if e is not None else None for e in embeddings]
        except Exception as e:
            logger.warning("[WatchStore] Batch embedding failed: %s", e)
            return [None] * len(titles)


# ── helpers ────────────────────────────────────────────────────────


def _cosine_sim(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _is_near_duplicate(a: str, b: str, threshold: float = 0.85) -> bool:
    from .utils import title_similar

    return title_similar(a, b, threshold)
