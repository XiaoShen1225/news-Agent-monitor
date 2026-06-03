"""PreferenceEngine: orchestrates three-layer memory for system prompt injection.

No longer runs LLM analysis directly — that's handled by MemoryManager.
This class reads L0/L1/L2 data + explicit overrides and formats them for display/prompt.
"""

import json
import logging
from pathlib import Path

from .preference_utils import now_iso

logger = logging.getLogger(__name__)

# Migrated from old data/user_preferences.json
OLD_PREFERENCES_FILE = Path("data/user_preferences.json")
OVERRIDES_FILE = Path("data/memory/explicit_overrides.json")
L1_PATTERNS_FILE = Path("data/memory/l1_patterns.json")
L2_PROFILE_FILE = Path("data/memory/l2_profile.json")


class PreferenceEngine:
    """Reads three-layer memory data and generates formatted preference text."""

    def __init__(self, track_store, llm_caller=None):
        self._track = track_store
        self._data = self._load()

    # ── file I/O ──────────────────────────────────────────────────────

    def _load(self) -> dict:
        # Migrate from old location if exists
        if OLD_PREFERENCES_FILE.exists() and not OVERRIDES_FILE.exists():
            try:
                old = json.loads(OLD_PREFERENCES_FILE.read_text(encoding="utf-8"))
                overrides = old.get("explicit_overrides", {})
                if overrides:
                    OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
                    OVERRIDES_FILE.write_text(
                        json.dumps(overrides, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(
                        "Migrated overrides from %s to %s",
                        OLD_PREFERENCES_FILE,
                        OVERRIDES_FILE,
                    )
            except (json.JSONDecodeError, OSError):
                pass

        if OVERRIDES_FILE.exists():
            try:
                return json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self):
        OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
        OVERRIDES_FILE.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── explicit overrides ────────────────────────────────────────────

    def get_overrides(self) -> dict:
        return self._data

    def set_override(self, interest: str, action: str, confidence: float = 0.9):
        self._data[interest.strip()] = {
            "action": action,
            "confidence": confidence,
            "updated_at": now_iso(),
        }
        self._save()

    # ── read three-layer data ─────────────────────────────────────────

    def get_current(self) -> dict:
        """Return combined L1 + L2 view."""
        l1 = self._load_json(L1_PATTERNS_FILE) or {}
        l2 = self._load_json(L2_PROFILE_FILE) or {}
        return {"l1": l1, "l2": l2}

    # ── formatting ────────────────────────────────────────────────────

    def format_for_display(self) -> str:
        """Human-readable preference summary for the preferences tool."""
        overrides = self.get_overrides()
        l1 = self._load_json(L1_PATTERNS_FILE) or {}
        l2 = self._load_json(L2_PROFILE_FILE) or {}

        parts = ["[偏好分析]"]

        # Overrides
        likes = [k for k, v in overrides.items() if v.get("action") == "like"]
        dislikes = [k for k, v in overrides.items() if v.get("action") == "dislike"]
        if likes:
            parts.append(f"明确喜欢: {', '.join(likes)}")
        if dislikes:
            parts.append(f"明确不喜欢: {', '.join(dislikes)}")

        # L2 profile
        if l2:
            identity = l2.get("identity", "")
            if identity:
                parts.append(f"身份推测: {identity}")
            stable = l2.get("stable_interests", [])
            if stable:
                items = [f"{i['name']}({i['strength']:.0%})" for i in stable[:5]]
                parts.append(f"稳定兴趣: {', '.join(items)}")
            habits = l2.get("reading_habits", "")
            if habits:
                parts.append(f"阅读习惯: {habits}")

        # L1 patterns
        if l1:
            active = l1.get("active_interests", [])
            if active:
                items = []
                for i in active[:5]:
                    name = i["name"]
                    trend = i.get("trend", "stable")
                    icon = (
                        "↑"
                        if trend == "rising"
                        else ("↓" if trend == "declining" else "→")
                    )
                    items.append(f"{name}[{icon}]")
                parts.append(f"近期活跃: {', '.join(items)}")
            emerging = l1.get("emerging", [])
            if emerging:
                parts.append(f"新兴兴趣: {', '.join(e['name'] for e in emerging)}")

        if len(parts) == 1:
            return "[偏好分析]\n暂无偏好数据"
        return "\n".join(parts)

    def format_for_prompt(self) -> str:
        """Generate the text injected into the system prompt (three-layer)."""
        overrides = self.get_overrides()
        l1 = self._load_json(L1_PATTERNS_FILE) or {}
        l2 = self._load_json(L2_PROFILE_FILE) or {}

        has_content = bool(overrides or l1 or l2)
        if not has_content:
            return ""

        lines = []
        likes = [k for k, v in overrides.items() if v.get("action") == "like"]
        dislikes = [k for k, v in overrides.items() if v.get("action") == "dislike"]

        # L2: 长期画像
        if l2:
            l2_lines = []
            identity = l2.get("identity", "")
            if identity:
                l2_lines.append(f" 身份推测: {identity}")
            stable = l2.get("stable_interests", [])
            if stable:
                items = [f"{i['name']}({i['strength']:.0%})" for i in stable[:5]]
                l2_lines.append(f" 稳定兴趣: {', '.join(items)}")
            habits = l2.get("reading_habits", "")
            if habits:
                l2_lines.append(f" 阅读习惯: {habits}")
            if l2_lines:
                lines.append("[用户长期画像]")
                lines.extend(l2_lines)

        # L1: 近期关注
        if l1:
            l1_lines = []
            active = l1.get("active_interests", [])
            if active:
                items = []
                for i in active[:5]:
                    name = i["name"]
                    trend = i.get("trend", "stable")
                    icon = (
                        "↑"
                        if trend == "rising"
                        else ("↓" if trend == "declining" else "→")
                    )
                    items.append(f"{name}({icon})")
                l1_lines.append(f" 活跃主题: {', '.join(items)}")
            emerging = l1.get("emerging", [])
            if emerging:
                l1_lines.append(f" 新兴兴趣: {', '.join(e['name'] for e in emerging)}")
            declining = l1.get("declining", [])
            if declining:
                l1_lines.append(f" 衰退兴趣: {', '.join(d['name'] for d in declining)}")
            if l1_lines:
                if lines:
                    lines.append("")
                lines.append("[近期关注]")
                lines.extend(l1_lines)

        # Overrides: 明确指示
        if likes or dislikes:
            if lines:
                lines.append("")
            lines.append("[用户明确指示]")
            if likes:
                lines.append(f" 喜欢: {', '.join(likes)}")
            if dislikes:
                lines.append(f" 不喜欢: {', '.join(dislikes)}")

        if not lines:
            return ""

        lines.append("")
        lines.append("(以上信息仅供参考，不要刻意迎合，不要在回答中主动提及偏好)")
        return "\n".join(lines)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _load_json(path: Path) -> dict | None:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return None
