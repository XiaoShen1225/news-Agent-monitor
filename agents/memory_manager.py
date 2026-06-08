"""MemoryManager: periodic memory distillation pipeline (L0 → L1 → L2).

Runs on APScheduler timer, independent of chat latency.
Reads TrackStore for incremental events, calls LLM for semantic extraction,
and manages the three-layer memory hierarchy.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .preference_utils import now_iso

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("data/memory")
L1_PATTERNS_FILE = MEMORY_DIR / "l1_patterns.json"
L2_PROFILE_FILE = MEMORY_DIR / "l2_profile.json"
OVERRIDES_FILE = MEMORY_DIR / "explicit_overrides.json"
AUDIT_LOG_FILE = MEMORY_DIR / "audit_log.jsonl"
PROMPTS_DIR = Path("agents/prompts")


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("Prompt file not found: %s", path)
    return ""


class MemoryManager:
    """Periodic memory distillation orchestrator."""

    def __init__(self, track_store, llm_config: dict = None):
        self._track = track_store
        self._llm_cfg = llm_config or {}
        self._last_analyzed_event_id = 0
        self._last_l1_run_at: str | None = None
        self._last_l2_run_at: str | None = None
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        # Resolve provider-specific config (e.g. llm.providers.openai)
        self._provider_cfg = self._resolve_provider_cfg()

    def _resolve_provider_cfg(self) -> dict:
        """Resolve effective LLM config from ``provider`` + ``providers`` sections."""
        provider_name = self._llm_cfg.get("provider", "openai")
        providers = self._llm_cfg.get("providers", {})
        pc = providers.get(provider_name, {})
        # Resolve ${ENV_VAR} placeholders
        import os

        def _resolve(value):
            if (
                isinstance(value, str)
                and value.startswith("${")
                and value.endswith("}")
            ):
                return os.environ.get(value[2:-1], "")
            return value

        return {
            "api_key": _resolve(pc.get("api_key", self._llm_cfg.get("api_key", ""))),
            "base_url": _resolve(
                pc.get(
                    "base_url",
                    self._llm_cfg.get("base_url", "https://api.openai.com/v1"),
                )
            ),
            "model": pc.get("model", self._llm_cfg.get("model", "gpt-4o-mini")),
        }

    # ── public entry ────────────────────────────────────────────────────

    async def run_cycle(self):
        """Main cycle: L0 extract → L1 aggregate → L2 update → quality check."""
        logger.info("[MemoryManager] Cycle started")
        try:
            await self._extract_l0()
        except Exception as e:
            logger.warning("[MemoryManager] L0 extraction failed: %s", e)

        try:
            if self._should_run_l1():
                await self._aggregate_l1()
        except Exception as e:
            logger.warning("[MemoryManager] L1 aggregation failed: %s", e)

        try:
            if self._should_run_l2():
                await self._update_l2()
        except Exception as e:
            logger.warning("[MemoryManager] L2 update failed: %s", e)

        try:
            self._run_maintenance()
        except Exception as e:
            logger.warning("[MemoryManager] Maintenance failed: %s", e)

        logger.info("[MemoryManager] Cycle completed")

    # ── L0: episodic extraction ─────────────────────────────────────────

    async def _extract_l0(self):
        """Extract L0 events from incremental chat messages."""
        max_id = self._track.get_max_event_id()
        if max_id <= self._last_analyzed_event_id:
            return

        sessions = self._track.get_chat_sessions(days=1)
        if not sessions:
            self._last_analyzed_event_id = max_id
            return

        # Collect new events per session
        new_sessions = []
        for sess in sessions:
            events = sess["events"]
            # Only process sessions with events after last analyzed id
            new_events = [e for e in events if e["id"] > self._last_analyzed_event_id]
            if new_events:
                new_sessions.append(
                    {"session_id": sess["session_id"], "events": new_events}
                )

        if not new_sessions:
            self._last_analyzed_event_id = max_id
            return

        prompt_template = _load_prompt("l0_extract.txt")
        if not prompt_template:
            self._last_analyzed_event_id = max_id
            return

        # Batch process: extract per session
        l0_events = []
        for sess in new_sessions:
            # Build conversation text from events
            lines = []
            source_ids = []
            for e in sess["events"]:
                meta = e.get("metadata")
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except json.JSONDecodeError:
                        meta = {}
                elif meta is None:
                    meta = {}
                role = meta.get("role", "unknown")
                prefix = "用户" if role == "user" else "AI"
                lines.append(f"{prefix}: {e.get('target_value', '')}")
                source_ids.append(e["id"])

            conversation = "\n".join(lines[-20:])  # last 20 messages max
            prompt = prompt_template + f"\n\n对话内容:\n{conversation}"

            try:
                result = await self._call_llm(prompt)
                parsed = self._parse_json(result)
                if parsed and parsed.get("topics"):
                    l0_events.append(
                        {
                            "session_id": sess["session_id"],
                            "source_event_ids": source_ids,
                            "topics": parsed.get("topics", []),
                            "entities": parsed.get("entities", []),
                            "summary": parsed.get("summary", ""),
                            "is_explicit_save": parsed.get("is_explicit", False),
                        }
                    )
            except Exception as e:
                logger.warning(
                    "[MemoryManager] L0 LLM call failed for session %s: %s",
                    sess["session_id"],
                    e,
                )
                continue

        if l0_events:
            count = self._track.insert_l0_events(l0_events)
            logger.info(
                "[MemoryManager] Extracted %d L0 events from %d sessions",
                count,
                len(new_sessions),
            )

        self._last_analyzed_event_id = max_id

    # ── L1: pattern aggregation ─────────────────────────────────────────

    def _should_run_l1(self) -> bool:
        since = (
            self._last_l1_run_at or (datetime.now() - timedelta(days=30)).isoformat()
        )
        new_count = self._track.get_l0_event_count_since(since)
        if new_count < 10:
            return False
        if self._last_l1_run_at:
            elapsed = (
                datetime.now() - datetime.fromisoformat(self._last_l1_run_at)
            ).total_seconds()
            if elapsed < 7200:  # 2 hours minimum
                return False
        return True

    async def _aggregate_l1(self):
        prompt_template = _load_prompt("l1_aggregate.txt")
        if not prompt_template:
            return

        l0_events = self._track.get_l0_events(status="active", limit=50)
        prev_l1 = self._load_json(L1_PATTERNS_FILE)

        # Gather frontend behavior from user_events
        recent = self._track.get_recent(days=30)
        clicked = []
        searches = []
        tag_filters: dict[str, int] = {}
        for e in recent:
            meta = e.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            elif meta is None:
                meta = {}

            if e["event_type"] == "click_link":
                clicked.append(meta.get("title", ""))
            elif e["event_type"] == "search":
                searches.append(e.get("target_value", ""))
            elif e["event_type"] == "filter_tag":
                tag = e.get("target_value", "")
                if tag:
                    tag_filters[tag] = tag_filters.get(tag, 0) + 1

        prompt = prompt_template + "\n\n数据:\n"
        prompt += f"L0 事件数: {len(l0_events)}\n"
        prompt += f"L0 主题: {json.dumps([e.get('topics', []) for e in l0_events[:10]], ensure_ascii=False)}\n"
        prompt += f"点击文章: {', '.join(clicked[:10])}\n" if clicked else ""
        prompt += f"搜索词: {', '.join(searches[:5])}\n" if searches else ""
        if tag_filters:
            prompt += f"标签过滤: {json.dumps(tag_filters, ensure_ascii=False)}\n"
        if prev_l1:
            prompt += f"上周期 L1: {json.dumps(prev_l1, ensure_ascii=False)}\n"

        try:
            result = await self._call_llm(prompt)
            parsed = self._parse_json(result)
            if parsed:
                self._save_json(L1_PATTERNS_FILE, parsed)
                self._last_l1_run_at = now_iso()
                logger.info("[MemoryManager] L1 aggregation completed")
        except Exception as e:
            logger.warning("[MemoryManager] L1 LLM call failed: %s", e)

    # ── L2: profile update ──────────────────────────────────────────────

    def _should_run_l2(self) -> bool:
        if self._last_l2_run_at:
            elapsed = (
                datetime.now() - datetime.fromisoformat(self._last_l2_run_at)
            ).total_seconds()
            if elapsed < 86400:  # 24 hours minimum
                return False
        patterns = self._load_json(L1_PATTERNS_FILE)
        if not patterns:
            return False
        # Check for persistent trend changes
        active = patterns.get("active_interests", [])
        changing = [i for i in active if i.get("trend") in ("rising", "declining")]
        return len(changing) >= 1

    async def _update_l2(self):
        prompt_template = _load_prompt("l2_profile.txt")
        if not prompt_template:
            return

        l1 = self._load_json(L1_PATTERNS_FILE)
        prev_l2 = self._load_json(L2_PROFILE_FILE)

        if not l1:
            return

        prompt = prompt_template + "\n\n数据:\n"
        prompt += f"L1 当前: {json.dumps(l1, ensure_ascii=False)}\n"
        if prev_l2:
            prompt += f"当前 L2 画像: {json.dumps(prev_l2, ensure_ascii=False)}\n"

        try:
            result = await self._call_llm(prompt)
            parsed = self._parse_json(result)
            if parsed:
                # Merge with existing profile (weighted fusion)
                if prev_l2:
                    parsed = self._fuse_profiles(prev_l2, parsed)
                self._save_json(L2_PROFILE_FILE, parsed)
                self._last_l2_run_at = now_iso()
                logger.info("[MemoryManager] L2 profile updated")
        except Exception as e:
            logger.warning("[MemoryManager] L2 LLM call failed: %s", e)

    @staticmethod
    def _fuse_profiles(old: dict, new: dict) -> dict:
        """Weighted fusion: keep old stable interests, adjust by new evidence."""
        # Simple fusion: new interests with strength changes override,
        # old interests without conflicting evidence are preserved
        old_interests = {i["name"]: i for i in old.get("stable_interests", [])}
        new_interests = {i["name"]: i for i in new.get("stable_interests", [])}

        fused = {}
        all_names = set(old_interests) | set(new_interests)
        for name in all_names:
            old_i = old_interests.get(name)
            new_i = new_interests.get(name)
            if old_i and new_i:
                # Weighted average: 70% old, 30% new
                fused[name] = {
                    "name": name,
                    "strength": round(
                        old_i["strength"] * 0.7 + new_i["strength"] * 0.3, 2
                    ),
                    "category": new_i.get("category", old_i.get("category", "")),
                }
            elif old_i:
                # Old interest not mentioned in new → slight decay
                fused[name] = {
                    "name": name,
                    "strength": round(old_i["strength"] * 0.9, 2),
                    "category": old_i.get("category", ""),
                }
            else:
                fused[name] = new_i

        # Remove interests that fell below threshold
        new["stable_interests"] = [v for v in fused.values() if v["strength"] >= 0.2]
        return new

    # ── maintenance ─────────────────────────────────────────────────────

    def _run_maintenance(self):
        """Run periodic cleanup: TTL expiry, cold storage purge."""
        self._track.expire_ttl_l0()
        self._track.purge_expired_l0()
        self._log_audit()

    def _log_audit(self):
        l0_active = self._track.get_l0_events(status="active", limit=1000)
        l0_soft = self._track.get_l0_events(status="soft_deleted", limit=1000)
        l1 = self._load_json(L1_PATTERNS_FILE)
        l2 = self._load_json(L2_PROFILE_FILE)

        entry = {
            "timestamp": now_iso(),
            "l0_active_count": len(l0_active),
            "l0_stale_count": len(l0_soft),
            "l1_interests_count": len(l1.get("active_interests", [])) if l1 else 0,
            "l2_interests_count": len(l2.get("stable_interests", [])) if l2 else 0,
        }
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── helpers ─────────────────────────────────────────────────────────

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM for analysis using resolved provider config."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self._provider_cfg.get("api_key") or "sk-placeholder",
            base_url=self._provider_cfg.get("base_url") or "https://api.openai.com/v1",
        )
        response = await client.chat.completions.create(
            model=self._provider_cfg.get("model") or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON object from text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
        return None

    @staticmethod
    def _load_json(path: Path) -> dict | None:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return None

    @staticmethod
    def _save_json(path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
