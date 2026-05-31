"""DeepAnalyzer: cross-site event clustering, entity recognition, timeline construction."""

import logging
from datetime import datetime

from .base_agent import BaseAgent
from .clustering import cluster_items

logger = logging.getLogger(__name__)


class DeepAnalyzer(BaseAgent):
    """Cross-site deep content analysis using LLM + vector clustering."""

    def __init__(self, config: dict):
        super().__init__("DeepAnalyzer", config)
        self._deep_cfg = config.get("deep_analysis", {}) or {}

    # ── event clustering ─────────────────────────────────────────────

    async def cluster_events(self, items: list[dict], vector_store) -> list[dict]:
        """Cluster items into cross-site events and name each cluster via LLM."""
        if not items or len(items) < 2:
            return []

        threshold = self._deep_cfg.get("cluster_similarity_threshold", 0.75)
        min_size = self._deep_cfg.get("min_event_items", 2)
        raw_clusters = cluster_items(items, vector_store, threshold, min_size)

        if not raw_clusters:
            return []

        # Name each cluster via LLM
        events = []
        for i, cluster in enumerate(raw_clusters):
            titles = [it.get("title", "")[:60] for it in cluster["items"][:8]]
            title_list = "\n".join(f"- {t}" for t in titles)

            event_name = await self._name_event(title_list, cluster)
            events.append(
                {
                    "event_id": f"evt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}",
                    "event_name": event_name,
                    "items": cluster["items"],
                    "sites": cluster["sites"],
                    "tags": cluster["tags"],
                    "size": cluster["size"],
                    "created_at": datetime.now().isoformat(),
                }
            )

        logger.info("[DeepAnalyzer] Named %d event clusters", len(events))
        return events

    async def _name_event(self, title_list: str, cluster: dict) -> str:
        """Ask LLM to generate a short Chinese event name for a cluster."""
        prompt = (
            f"以下是从不同新闻站点抓取的相关标题（共 {cluster['size']} 条）：\n"
            f"{title_list}\n\n"
            "这些标题可能指向同一个新闻事件。请为这个事件起一个简短的中文名称（10字以内），只输出事件名称，不要其他内容。"
        )

        try:
            name = await self.call_llm_async(
                system_prompt="你是一个新闻事件命名助手。根据一组相关标题，提炼出简洁准确的事件名称。",
                user_prompt=prompt,
                max_tokens=30,
                temperature=0.2,
                fallback=None,
            )
            if name:
                return name.strip()[:20]
        except Exception as e:
            logger.warning("[DeepAnalyzer] Event naming failed: %s", e)

        # Fallback: use most frequent keyword from titles
        from collections import Counter

        words = []
        for it in cluster["items"]:
            title = it.get("title", "")
            words.extend(title[:20].split())
        if words:
            top = Counter(words).most_common(1)[0][0]
            return f"关于{top}的事件"
        return f"事件簇({cluster['size']}条)"

    # ── entity recognition ────────────────────────────────────────────

    async def extract_entities(self, items: list[dict]) -> list[dict]:
        """Batch-extract named entities from item titles via LLM."""
        if not items:
            return []

        batch_size = self._deep_cfg.get("entity_batch_size", 50)
        all_entities = []

        for batch_start in range(0, len(items), batch_size):
            batch = items[batch_start : batch_start + batch_size]
            indexed = [
                (i, it.get("title", ""))
                for i, it in enumerate(batch)
                if it.get("title")
            ]

            if not indexed:
                continue

            title_lines = "\n".join(
                f"[{idx}] {title[:80]}" for idx, title in indexed[:batch_size]
            )

            try:
                result = await self._extract_entities_batch(title_lines)
                all_entities.extend(result)
            except Exception as e:
                logger.warning("[DeepAnalyzer] Entity extraction batch failed: %s", e)

        # Deduplicate by entity name
        seen = {}
        for ent in all_entities:
            name = ent.get("name", "")
            if name and name not in seen:
                seen[name] = ent
                seen[name]["mentions"] = 1
            elif name:
                seen[name]["mentions"] += 1

        entities = sorted(seen.values(), key=lambda e: e["mentions"], reverse=True)
        logger.info("[DeepAnalyzer] Extracted %d unique entities", len(entities))
        return entities

    async def _extract_entities_batch(self, title_lines: str) -> list[dict]:
        prompt = (
            "从以下新闻标题中提取命名实体（人物、机构、地点、产品、事件类型），"
            "返回 JSON 数组，每个元素格式为：\n"
            '{"name": "实体名", "type": "PER|ORG|LOC|PROD|EVENT"}\n\n'
            f"{title_lines}\n\n"
            "只输出 JSON 数组，不要其他内容。"
        )

        response = await self.call_llm_async(
            system_prompt='你是一个中文命名实体识别助手。只输出 JSON，格式：[{"name":"...","type":"..."}]',
            user_prompt=prompt,
            max_tokens=800,
            temperature=0.1,
            fallback="[]",
        )

        try:
            return self.parse_json_response(response)
        except Exception:
            return []

    # ── timeline ──────────────────────────────────────────────────────

    async def build_timeline(
        self, event_name: str, event_items: list[dict], store=None
    ) -> dict:
        """Build a time-sorted narrative for an event using historical data."""
        if not event_items:
            return {"event_name": event_name, "timeline": [], "summary": ""}

        # Sort items by snapshot time
        sorted_items = sorted(
            event_items,
            key=lambda it: it.get("snapshot_time", "") or it.get("published", "") or "",
        )

        timeline = []
        for it in sorted_items:
            timeline.append(
                {
                    "time": it.get("snapshot_time", "") or it.get("published", ""),
                    "site": it.get("site_name", ""),
                    "title": it.get("title", ""),
                    "url": it.get("url", ""),
                    "tag": it.get("tag", ""),
                    "sentiment": it.get("sentiment", ""),
                }
            )

        # Generate timeline summary via LLM
        summary = await self._summarize_timeline(event_name, timeline)

        return {
            "event_name": event_name,
            "timeline": timeline,
            "summary": summary,
            "item_count": len(timeline),
        }

    async def _summarize_timeline(self, event_name: str, timeline: list) -> str:
        if not timeline:
            return "暂无时间线数据。"

        entries = "\n".join(
            f"- {t['time'][:19] if t['time'] else '?'} [{t['site']}] {t['title'][:80]}"
            for t in timeline[:15]
        )

        prompt = (
            f"事件「{event_name}」的时间线（共 {len(timeline)} 条）：\n"
            f"{entries}\n\n"
            "请用 2-4 句中文总结这个事件的发展脉络，不超过 120 字。"
        )

        try:
            result = await self.call_llm_async(
                system_prompt="你是一个新闻事件分析助手。基于时间线数据，用简洁中文总结事件发展。",
                user_prompt=prompt,
                max_tokens=200,
                temperature=0.3,
                fallback=None,
            )
            return result or f"共 {len(timeline)} 条相关报道。"
        except Exception as e:
            logger.warning("[DeepAnalyzer] Timeline summary failed: %s", e)
            return f"共 {len(timeline)} 条相关报道。"

    # ── full analysis ─────────────────────────────────────────────────

    async def run_async(
        self, all_new_items: list[dict], vector_store, data_store
    ) -> dict:
        """Run full deep analysis: cluster events + extract entities."""
        if not all_new_items:
            return {"events": [], "entities": []}

        # Annotate each item with site_name before clustering
        for it in all_new_items:
            if "site_name" not in it:
                it["site_name"] = it.get("site", "")

        events = await self.cluster_events(all_new_items, vector_store)
        entities = await self.extract_entities(all_new_items)

        # Save to datastore if available
        if data_store and events:
            data_store.save_events(events)
        if data_store and entities:
            data_store.save_entities(entities)

        return {
            "events": events,
            "entities": entities,
            "event_count": len(events),
            "entity_count": len(entities),
        }

    # ── sync wrapper ──────────────────────────────────────────────────

    def run(self, all_new_items: list, vector_store, data_store) -> dict:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(all_new_items, vector_store, data_store))
        raise RuntimeError("DeepAnalyzer.run() in async context — use run_async()")
