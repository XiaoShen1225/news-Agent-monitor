"""MemoryManager: funnel architecture for preference distillation.

Pipeline: collect raw data → jieba keyword cloud → single LLM call → profile.

Jieba provides the keyword statistics (word cloud); the LLM adds semantic
understanding.  If the LLM call fails, the jieba cloud is saved directly as
the fallback profile — the system always produces output.
"""

import json
import logging
import os
import re
from pathlib import Path

from .preference_utils import now_iso

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("data/memory")
CHECKPOINT_FILE = MEMORY_DIR / "checkpoint.json"
L1_PATTERNS_FILE = MEMORY_DIR / "l1_patterns.json"
L2_PROFILE_FILE = MEMORY_DIR / "l2_profile.json"
AUDIT_LOG_FILE = MEMORY_DIR / "audit_log.jsonl"

# ── Prompt: LLM turns keyword cloud into structured profile ─────────

_PROFILE_PROMPT = """你是一个用户画像分析器。根据用户近期的聊天关键词和行为数据，生成用户兴趣画像。

输入数据包含：
- 聊天关键词（jieba 分词 + TF-IDF 权重）
- 点击的文章标题
- 搜索查询词

请分析并输出以下 JSON 格式（仅输出 JSON，不要其他文字）：

{
  "active_interests": [
    {"name": "兴趣名", "weight": 0.8, "trend": "rising|stable|declining"}
  ],
  "emerging": [{"name": "新兴兴趣", "weight": 0.5}],
  "declining": [{"name": "衰退兴趣", "weight": 0.2}],
  "stable_interests": [
    {"name": "兴趣名", "strength": 0.7, "category": "科技|财经|时政|娱乐|体育|教育|健康|科学|综合"}
  ],
  "identity": "简短身份推测（15字内）",
  "reading_habits": "阅读习惯描述（20字内）"
}

规则：
- 权重/强度范围 0.0-1.0，反映兴趣的确定程度
- 过滤掉明显的噪音/寒暄词
- 合并同义或高度相关的关键词
- 兴趣名使用简洁的短语（≤8字）
- emerging 是新出现且证据尚不充分的兴趣
- active_interests 取 5-10 个最重要的
- stable_interests 是经过平滑的长期兴趣，取 3-8 个"""


def _extract_keyword_cloud(texts: list[str], top_k: int = 30) -> list[dict]:
    """Run jieba TF-IDF on a list of texts, return sorted keyword list."""
    import jieba.analyse

    # Strip URLs and markdown before extraction
    cleaned = []
    for t in texts:
        t = re.sub(r"https?://\S+", " ", t)  # URLs
        t = re.sub(
            r"#{1,6}\s|[*_~`]{1,3}|\n-+\n|\[([^\]]+)\]\([^)]+\)", " ", t
        )  # markdown
        cleaned.append(t)

    combined = " ".join(cleaned)
    if not combined.strip():
        return []
    raw = jieba.analyse.extract_tags(combined, topK=top_k, withWeight=True)
    result = []
    for kw, w in raw:
        kw = kw.strip()
        if len(kw) < 2:
            continue
        if re.match(r"^[#\-\*=~>|_./\\]+$", kw):
            continue
        if re.match(r"^\d+(\.\d+)?$", kw):
            continue
        if re.match(r"^[a-zA-Z]$", kw):
            continue
        result.append({"keyword": kw, "weight": round(w, 2)})
    return result


class MemoryManager:
    """Funnel: collect → jieba → LLM → profile.

    One LLM call per cycle. Jieba word cloud is always available as fallback.
    """

    def __init__(self, track_store, llm_config: dict = None, memory_cfg: dict = None):
        self._track = track_store
        self._full_config = llm_config or {}
        self._llm_cfg = self._full_config.get("llm", {})
        self._memory_cfg = memory_cfg or {}
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._provider_cfg = self._resolve_provider_cfg()

        ck = self._load_checkpoint()
        self._last_event_id: int = ck.get("last_event_id", 0)
        self._last_run_at: str | None = ck.get("last_run_at")

        logger.info(
            "[MemoryManager] checkpoint=%d last_run=%s",
            self._last_event_id,
            self._last_run_at or "never",
        )

    # ── checkpoint ───────────────────────────────────────────────────

    def _load_checkpoint(self) -> dict:
        if CHECKPOINT_FILE.exists():
            try:
                return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_checkpoint(self):
        CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_FILE.write_text(
            json.dumps(
                {
                    "last_event_id": self._last_event_id,
                    "last_run_at": self._last_run_at,
                    "updated_at": now_iso(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ── public entry ─────────────────────────────────────────────────

    async def run_cycle(self):
        logger.info("[MemoryManager] Cycle start")
        try:
            await self._distill()
        except Exception as e:
            logger.warning("[MemoryManager] Cycle failed: %s", e)
        try:
            self._prune()
        except Exception as e:
            logger.warning("[MemoryManager] Prune failed: %s", e)
        self._save_checkpoint()
        logger.info("[MemoryManager] Cycle done")

    # ── core: collect → jieba → LLM → profile ────────────────────────

    async def _distill(self):
        # 1. COLLECT raw text from recent activity
        chat_texts, click_titles, searches = self._collect_data()
        all_text = chat_texts + click_titles + searches
        if not all_text:
            logger.info("[MemoryManager] No new data to distill")
            return

        # 2. JIEBA keyword cloud
        cloud = _extract_keyword_cloud(all_text, top_k=40)
        if not cloud:
            return
        logger.info(
            "[MemoryManager] Keyword cloud: %s",
            ", ".join(f"{c['keyword']}({c['weight']})" for c in cloud[:10]),
        )

        # 3. Build prompt
        prompt = self._build_prompt(cloud, click_titles, searches)

        # 4. LLM call (single)
        prev_l2 = self._load_json(L2_PROFILE_FILE)
        profile = await self._call_llm_for_profile(prompt)

        if profile:
            # LLM succeeded — fuse with previous L2
            if prev_l2:
                profile = self._fuse(prev_l2, profile)
            logger.info("[MemoryManager] LLM profile generated")
        else:
            # LLM failed — build profile from jieba cloud directly
            profile = self._cloud_to_profile(cloud, prev_l2)
            logger.info("[MemoryManager] Fallback to jieba-only profile")

        # 5. Save
        self._save_json(L2_PROFILE_FILE, profile)
        # Also save L1 (simplified — just the cloud for display)
        l1_data = {
            "active_interests": [
                {
                    "name": c["keyword"],
                    "weight": round(min(1.0, c["weight"] * 5), 2),
                    "trend": "stable",
                }
                for c in cloud[:15]
            ],
            "emerging": [],
            "declining": [],
            "updated_at": now_iso(),
        }
        self._save_json(L1_PATTERNS_FILE, l1_data)
        self._last_run_at = now_iso()

    def _collect_data(self) -> tuple[list[str], list[str], list[str]]:
        """Gather raw text since last checkpoint.

        User messages are repeated (weighted higher) for jieba cloud.
        Assistant messages are used for context only.
        """
        lookback = self._memory_cfg.get("lookback_days", 7)
        recent = self._track.get_recent(days=lookback)

        user_texts: list[str] = []
        assistant_texts: list[str] = []
        click_titles: list[str] = []
        searches: list[str] = []
        max_id = self._last_event_id

        for e in recent:
            eid = e.get("id", 0)
            if eid > max_id:
                max_id = eid

            if e["event_type"] == "chat_message":
                text = e.get("target_value", "")
                if not text:
                    continue
                meta = e.get("metadata")
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except json.JSONDecodeError:
                        meta = {}
                role = (meta or {}).get("role", "")
                if role == "user":
                    user_texts.append(text)
                else:
                    assistant_texts.append(text)
            elif e["event_type"] == "click_link":
                meta = e.get("metadata")
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except json.JSONDecodeError:
                        meta = {}
                title = (meta or {}).get("title", "")
                if title:
                    click_titles.append(title)
            elif e["event_type"] == "search":
                q = e.get("target_value", "")
                if q:
                    searches.append(q)

        self._last_event_id = max_id
        # User messages carry primary interest signal — repeat 3x for emphasis
        chat_texts = user_texts * 3 + assistant_texts
        logger.info(
            "[MemoryManager] Collected: %d user msgs, %d assistant, %d clicks, %d searches",
            len(user_texts),
            len(assistant_texts),
            len(click_titles),
            len(searches),
        )
        return chat_texts, click_titles, searches

    def _build_prompt(
        self, cloud: list[dict], click_titles: list[str], searches: list[str]
    ) -> str:
        lines = [_PROFILE_PROMPT, "", "=== 用户数据 ==="]
        lines.append(f"\n[关键词云] (jieba TF-IDF, top {len(cloud)}):")
        for c in cloud:
            lines.append(f"  {c['keyword']}: {c['weight']}")
        if click_titles:
            lines.append(f"\n[点击文章标题] ({len(click_titles)} 篇):")
            for t in click_titles[:20]:
                lines.append(f"  - {t}")
        if searches:
            lines.append("\n[搜索查询]:")
            for s in searches:
                lines.append(f"  - {s}")
        return "\n".join(lines)

    # ── LLM ──────────────────────────────────────────────────────────

    def _resolve_provider_cfg(self) -> dict:
        provider_name = self._llm_cfg.get("provider", "openai")
        providers = self._llm_cfg.get("providers", {})
        pc = providers.get(provider_name, {})

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

    async def _call_llm_for_profile(self, prompt: str) -> dict | None:
        """Single LLM call with semantic cache. Returns parsed profile dict or None."""
        api_key = self._provider_cfg.get("api_key") or ""
        if not api_key or api_key == "sk-placeholder":
            logger.info("[MemoryManager] No API key — using jieba fallback")
            return None

        # Check semantic cache first
        model_name = self._provider_cfg.get("model", "")
        try:
            from .semantic_cache import get_cache

            cache = get_cache()
            cached = cache.get(prompt, model=model_name)
            if cached:
                return self._parse_json(cached)
        except Exception:
            pass  # Cache failure should not block the LLM call

        try:
            from .provider_factory import create_provider

            model = create_provider(self._full_config)
            response = await model.ainvoke([{"role": "user", "content": prompt}])
            text = (response.content or "").strip()
            # Store in cache
            try:
                cache.set(prompt, text, model=model_name)
            except Exception:
                pass
            return self._parse_json(text)
        except Exception as e:
            logger.warning("[MemoryManager] LLM call failed, using fallback: %s", e)
            return None

    # ── fallback: jieba cloud → profile without LLM ─────────────────

    def _cloud_to_profile(self, cloud: list[dict], prev_l2: dict | None) -> dict:
        """Build a basic profile from the keyword cloud alone."""
        interests = []
        for c in cloud[:10]:
            interests.append(
                {
                    "name": c["keyword"],
                    "strength": round(min(1.0, c["weight"] * 5), 2),
                    "category": "综合",
                }
            )
        profile = {
            "stable_interests": interests,
            "identity": "",
            "reading_habits": f"关注: {', '.join(c['keyword'] for c in cloud[:5])}",
            "updated_at": now_iso(),
        }
        if prev_l2:
            profile = self._fuse(prev_l2, profile)
        return profile

    # ── fusion ───────────────────────────────────────────────────────

    @staticmethod
    def _fuse(old: dict, new: dict) -> dict:
        """Weighted merge: 70% old, 30% new."""
        old_map = {i["name"]: i for i in old.get("stable_interests", [])}
        new_map = {i["name"]: i for i in new.get("stable_interests", [])}

        fused = {}
        for name in set(old_map) | set(new_map):
            o = old_map.get(name)
            n = new_map.get(name)
            if o and n:
                fused[name] = {
                    "name": name,
                    "strength": round(o["strength"] * 0.7 + n["strength"] * 0.3, 2),
                    "category": n.get("category", o.get("category", "")),
                }
            elif o:
                fused[name] = {
                    "name": name,
                    "strength": round(o["strength"] * 0.9, 2),
                    "category": o.get("category", ""),
                }
            else:
                fused[name] = n

        result = dict(new)
        result["stable_interests"] = [
            v for v in fused.values() if v["strength"] >= 0.15
        ]
        return result

    # ── maintenance ──────────────────────────────────────────────────

    def _prune(self):
        self._track.expire_ttl_l0()
        self._track.purge_expired_l0()

    def get_status(self) -> dict:
        l1 = self._load_json(L1_PATTERNS_FILE)
        l2 = self._load_json(L2_PROFILE_FILE)
        return {
            "checkpoint_event_id": self._last_event_id,
            "last_run_at": self._last_run_at,
            "l1_interests": len(l1.get("active_interests", [])) if l1 else 0,
            "l2_interests": len(l2.get("stable_interests", [])) if l2 else 0,
        }

    # ── JSON helpers ─────────────────────────────────────────────────

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
