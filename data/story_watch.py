"""StoryWatchStore: track news stories and detect follow-up coverage."""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class StoryWatchStore:
    """Persistent store for tracked stories with lifecycle management.

    Lifecycle: active → completed (user) / dormant (auto, no matches in 30d)
    Dormant stories are automatically cleaned up after 90 days.

    Storage: ``data/story_watch.json``
    """

    def __init__(self, file_path: str = "data/story_watch.json"):
        self._path = Path(file_path)
        self._data = self._load()

    # ── file I/O ────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("StoryWatchStore: corrupt file, starting fresh")
        return {"stories": [], "config": {}}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── story CRUD ──────────────────────────────────────────────────

    def add_story(
        self,
        title: str,
        url: str = "",
        tags: list = None,
        entities: list = None,
        embedding: list[float] = None,
        source_site: str = "",
    ) -> dict:
        """Add a story to the watch list. Returns status dict."""
        title = title.strip()
        if not title:
            return {"ok": False, "msg": "故事标题不能为空"}

        # Dedup: check if a story with very similar title already exists
        for s in self._data.get("stories", []):
            if s["title"] == title:
                return {
                    "ok": True,
                    "msg": f"该故事已在追踪列表中（状态: {s['status']}）",
                }

        story_id = f"story_{uuid.uuid4().hex[:10]}"
        now = _now_iso()
        story = {
            "id": story_id,
            "title": title,
            "url": url or "",
            "source_site": source_site,
            "tags": tags or [],
            "entities": entities or [],
            "embedding": embedding or [],
            "status": "active",
            "created_at": now,
            "last_match_at": None,
            "match_count": 0,
            "match_history": [],
            "completed_at": None,
        }
        self._data.setdefault("stories", []).append(story)
        self._save()
        logger.info("[StoryWatch] Added story: %s", title[:60])
        return {
            "ok": True,
            "msg": f"已开始追踪故事「{title[:40]}」",
            "story_id": story_id,
        }

    def remove_story(self, story_id: str = None, title: str = None) -> dict:
        """Remove a story from tracking (complete/unwatch)."""
        stories = self._data.get("stories", [])
        before = len(stories)
        if story_id:
            self._data["stories"] = [s for s in stories if s["id"] != story_id]
        elif title:
            self._data["stories"] = [s for s in stories if s["title"] != title.strip()]
        else:
            return {"ok": False, "msg": "请提供 story_id 或 title"}

        removed = before - len(self._data["stories"])
        if removed > 0:
            self._save()
            return {"ok": True, "msg": f"已移除 {removed} 个追踪故事"}
        return {"ok": False, "msg": "未找到匹配的追踪故事"}

    def complete_story(self, story_id: str) -> dict:
        """Mark a story as completed (story concluded, stop matching)."""
        for s in self._data.get("stories", []):
            if s["id"] == story_id:
                s["status"] = "completed"
                s["completed_at"] = _now_iso()
                self._save()
                return {"ok": True, "msg": f"故事「{s['title'][:40]}」已标记为完结"}
        return {"ok": False, "msg": "未找到该故事"}

    def list_stories(self, status: str = None) -> list[dict]:
        """List tracked stories, optionally filtered by status."""
        self._auto_update_lifecycle()
        stories = self._data.get("stories", [])
        result = []
        for s in stories:
            if status and s["status"] != status:
                continue
            result.append(
                {
                    "id": s["id"],
                    "title": s["title"],
                    "url": s.get("url", ""),
                    "status": s["status"],
                    "source_site": s.get("source_site", ""),
                    "tags": s.get("tags", []),
                    "match_count": s.get("match_count", 0),
                    "created_at": s.get("created_at", ""),
                    "last_match_at": s.get("last_match_at"),
                }
            )
        return result

    # ── matching ────────────────────────────────────────────────────

    def check_new_items(
        self,
        new_items: list[dict],
        vector_store,
        threshold: float = None,
    ) -> list[dict]:
        """Check new items against all active watched stories.

        Returns list of matches: [{story_id, story_title, item_title, item_url, site, score}].
        Only active stories are checked. Matches respect cooldown (1 match per story per 12h).
        """
        self._auto_update_lifecycle()
        stories = self._data.get("stories", [])

        active = [s for s in stories if s["status"] == "active"]
        if not active or not new_items:
            return []

        if threshold is None:
            threshold = self._data.get("config", {}).get("similarity_threshold", 0.7)

        cooldown_hours = self._data.get("config", {}).get("match_cooldown_hours", 12)

        # Build item embeddings
        item_titles = [it.get("title", "") for it in new_items]
        item_embeddings = self._get_embeddings(item_titles, vector_store)

        matches = []
        now = datetime.now()

        for story in active:
            story_emb = story.get("embedding", [])
            if not story_emb:
                continue

            # Cooldown check
            last_match = story.get("last_match_at")
            if last_match:
                try:
                    last_dt = datetime.fromisoformat(last_match)
                    if (now - last_dt) < timedelta(hours=cooldown_hours):
                        continue
                except ValueError:
                    pass

            best_score = 0.0
            best_item = None
            for i, item_emb in enumerate(item_embeddings):
                if not item_emb:
                    continue
                score = _cosine_sim(story_emb, item_emb)
                if score >= threshold and score > best_score:
                    # Skip if title is near-identical (same article, not follow-up)
                    it_title = new_items[i].get("title", "")
                    if _is_near_duplicate(it_title, story["title"]):
                        continue
                    best_score = score
                    best_item = new_items[i]

            if best_item:
                match = {
                    "story_id": story["id"],
                    "story_title": story["title"],
                    "item_title": best_item.get("title", ""),
                    "item_url": best_item.get("url", ""),
                    "site": best_item.get("site_name", ""),
                    "score": round(best_score, 3),
                }
                matches.append(match)
                self._record_match(story, match)

        if matches:
            logger.info("[StoryWatch] %d follow-up matches found", len(matches))
        return matches

    def _record_match(self, story: dict, match: dict):
        """Update story match history and persist."""
        now = _now_iso()
        story["last_match_at"] = now
        story["match_count"] = story.get("match_count", 0) + 1
        history = story.setdefault("match_history", [])
        history.append(
            {
                "time": now,
                "title": match["item_title"][:100],
                "url": match["item_url"],
                "score": match["score"],
            }
        )
        # Keep last 20 matches
        if len(history) > 20:
            story["match_history"] = history[-20:]
        self._save()

    # ── lifecycle management ────────────────────────────────────────

    def _auto_update_lifecycle(self):
        """Automatically update story lifecycles based on match activity.

        - active + no match in 30 days → dormant
        - dormant + 90 days since last match → removed
        """
        stories = self._data.get("stories", [])
        if not stories:
            return

        now = datetime.now()
        dormant_days = self._data.get("config", {}).get("dormant_after_days", 30)
        remove_days = self._data.get("config", {}).get("remove_dormant_after_days", 90)

        changed = False
        kept = []

        for s in stories:
            if s["status"] == "active":
                last = s.get("last_match_at")
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if (now - last_dt) > timedelta(days=dormant_days):
                            s["status"] = "dormant"
                            logger.info(
                                "[StoryWatch] Story '%s' → dormant (no match in %d days)",
                                s["title"][:50],
                                dormant_days,
                            )
                            changed = True
                    except ValueError:
                        pass
                elif s.get("created_at"):
                    # Never matched — check from creation
                    try:
                        created_dt = datetime.fromisoformat(s["created_at"])
                        if (now - created_dt) > timedelta(days=dormant_days):
                            s["status"] = "dormant"
                            changed = True
                    except ValueError:
                        pass
            elif s["status"] == "dormant":
                last = s.get("last_match_at") or s.get("created_at", "")
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if (now - last_dt) > timedelta(days=remove_days):
                            logger.info(
                                "[StoryWatch] Removing dormant story '%s'",
                                s["title"][:50],
                            )
                            changed = True
                            continue
                    except ValueError:
                        pass
                else:
                    changed = True
                    continue
            kept.append(s)

        if changed:
            self._data["stories"] = kept
            self._save()

    def get_dormant_stories(self) -> list[dict]:
        """Return dormant stories for user review."""
        return self.list_stories(status="dormant")

    def reactivate_story(self, story_id: str) -> dict:
        """Reactivate a dormant story."""
        for s in self._data.get("stories", []):
            if s["id"] == story_id:
                s["status"] = "active"
                self._save()
                return {"ok": True, "msg": f"已重新激活追踪「{s['title'][:40]}」"}
        return {"ok": False, "msg": "未找到该故事"}

    # ── config ──────────────────────────────────────────────────────

    def load_config(self, config: dict):
        """Sync story watch config from config.yaml."""
        cfg = config.get("story_watch", {}) or {}
        self._data["config"] = {
            "similarity_threshold": cfg.get("similarity_threshold", 0.7),
            "match_cooldown_hours": cfg.get("match_cooldown_hours", 12),
            "dormant_after_days": cfg.get("dormant_after_days", 30),
            "remove_dormant_after_days": cfg.get("remove_dormant_after_days", 90),
        }
        self._save()

    def get_config(self) -> dict:
        return self._data.get("config", {})

    # ── embedding helper ────────────────────────────────────────────

    def compute_embedding(self, text: str, vector_store) -> list[float] | None:
        """Compute embedding for a single text via VectorStore's embedding function."""
        try:
            ef = vector_store._ef
            result = ef([text])
            if result and result[0] is not None:
                return [float(v) for v in result[0]]
        except Exception as e:
            logger.warning("[StoryWatch] Embedding failed: %s", e)
        return None

    @staticmethod
    def _get_embeddings(titles: list[str], vector_store) -> list[list[float] | None]:
        """Batch compute embeddings via VectorStore."""
        try:
            ef = vector_store._ef
            embeddings = ef(titles)
            return [list(e) if e is not None else None for e in embeddings]
        except Exception as e:
            logger.warning("[StoryWatch] Batch embedding failed: %s", e)
            return [None] * len(titles)


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _is_near_duplicate(a: str, b: str, threshold: float = 0.85) -> bool:
    """Check if two titles are near-duplicates (same article, not a follow-up)."""
    from .utils import title_similar

    return title_similar(a, b, threshold)
