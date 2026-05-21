"""AnalyzerAgent: compare snapshots, detect changes, compute trends."""

import asyncio
import logging
from datetime import datetime

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class AnalyzerAgent(BaseAgent):
    def __init__(self, config: dict, data_store=None):
        super().__init__("Analyzer", config)
        self.store = data_store

    # ── sync (wraps async) ──────────────────────────────────────────

    def run(self, current_items: list, site_name: str, content_hash: str) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(current_items, site_name, content_hash))
        raise RuntimeError("Analyzer.run() in async context — use run_async()")

    # ── async ───────────────────────────────────────────────────────

    async def run_async(self, current_items: list, site_name: str, content_hash: str) -> dict:
        """Compare current items with previous snapshot."""
        logger.info("[Analyzer] Analyzing %d items for %s", len(current_items), site_name)

        previous = self.store.get_last_snapshot(site_name) if self.store else None
        prev_items = previous.get("items", []) if previous else []

        new_items, removed_items, modified_items = self._diff_items(prev_items, current_items)

        total_changes = len(new_items) + len(removed_items) + len(modified_items)

        trends = self._compute_trends(site_name, current_items)

        # Sentiment analysis (only for new/modified items if changes exist)
        sentiment_enabled = self.config.get("sentiment", {}).get("enabled", True)
        if sentiment_enabled and current_items:
            await self._analyze_sentiment_batch_async(current_items)

        report = {
            "site_name": site_name,
            "timestamp": datetime.now().isoformat(),
            "content_hash": content_hash,
            "current_count": len(current_items),
            "previous_count": len(prev_items),
            "new_items": new_items,
            "removed_items": removed_items,
            "modified_items": modified_items,
            "total_changes": total_changes,
            "has_changes": total_changes > 0 or not previous,
            "is_first_run": not previous,
            "tag_distribution": self._tag_distribution(current_items),
            "trends": trends,
            "sentiment_distribution": self._sentiment_distribution(current_items),
        }

        report["llm_summary"] = await self._generate_summary_async(report)

        logger.info(
            "[Analyzer] Changes: %d new, %d removed, %d modified",
            len(new_items),
            len(removed_items),
            len(modified_items),
        )

        return report

    async def _generate_summary_async(self, report: dict) -> str:
        if not report.get("has_changes") or report.get("is_first_run"):
            return None

        new_count = len(report.get("new_items", []))
        removed_count = len(report.get("removed_items", []))
        total_count = report.get("current_count", 0)
        tag_dist = report.get("tag_distribution", {})
        direction = report.get("trends", {}).get("direction", "stable")

        new_titles = [it.get("title", "") for it in report.get("new_items", [])[:8]]
        removed_titles = [it.get("title", "") for it in report.get("removed_items", [])[:5]]
        top_tags = list(tag_dist.items())[:5]

        user_prompt = f"""当前抓取到百度新闻首页共 {total_count} 条新闻。

变化情况：
- 新增 {new_count} 条
- 移除 {removed_count} 条
- 趋势方向：{direction}

分类分布 Top 5：{top_tags}

新增新闻标题示例：{new_titles}
移除新闻标题示例：{removed_titles}

请用 2-3 句简短的中文总结本次新闻更新的特点。例如：集中在哪些领域、是否有重大事件迹象、新闻量变化是否异常。"""

        try:
            summary = await self.call_llm_async(
                system_prompt="你是一个新闻数据分析助手。根据提供的新闻抓取数据，用简洁的中文总结本次更新的特点。控制在 80 字以内。",
                user_prompt=user_prompt,
                max_tokens=200,
                temperature=0.3,
                fallback=None,
            )
            if summary:
                logger.info("[Analyzer] LLM summary generated: %s", summary[:80])
            return summary
        except Exception as e:
            logger.warning("[Analyzer] LLM summary failed, continuing without it: %s", e)
            return None

    def _diff_items(self, prev: list, curr: list) -> tuple:
        prev_titles = {item.get("title", ""): item for item in prev}
        curr_titles = {item.get("title", ""): item for item in curr}

        new_items = [
            {"title": t, **curr_titles[t]}
            for t in curr_titles if t and t not in prev_titles
        ]
        removed_items = [
            {"title": t, **prev_titles[t]}
            for t in prev_titles if t and t not in curr_titles
        ]

        modified_items = []
        for t in curr_titles:
            if t and t in prev_titles:
                prev_item = prev_titles[t]
                curr_item = curr_titles[t]
                if prev_item.get("summary") != curr_item.get("summary") or \
                   prev_item.get("tag") != curr_item.get("tag"):
                    modified_items.append({
                        "title": t,
                        "previous": prev_item,
                        "current": curr_item,
                    })

        return new_items, removed_items, modified_items

    def _tag_distribution(self, items: list) -> dict:
        dist = {}
        for item in items:
            tag = item.get("tag", "其他") or "其他"
            dist[tag] = dist.get(tag, 0) + 1
        return dict(sorted(dist.items(), key=lambda x: x[1], reverse=True))

    async def _analyze_sentiment_batch_async(self, items: list):
        """Classify sentiment for items without one using LLM batch inference."""
        candidates = [it for it in items if not it.get("sentiment")]
        if not candidates:
            return

        titles = [it.get("title", "") for it in candidates[:30]]

        user_prompt = "请对以下新闻标题逐一进行情感分类，只返回 positive、negative 或 neutral。\n\n"
        for i, t in enumerate(titles, 1):
            user_prompt += f"{i}. {t}\n"
        user_prompt += "\n请按行输出，每行格式为「序号. 分类」，不要额外解释。"

        try:
            result = await self.call_llm_async(
                system_prompt="你是一个新闻情感分析助手。只输出分类结果，每行一个。",
                user_prompt=user_prompt,
                max_tokens=500,
                temperature=0.0,
            )
            if result:
                for line in result.strip().split("\n"):
                    line = line.strip()
                    if "." in line:
                        parts = line.split(".", 1)
                        try:
                            idx = int(parts[0].strip()) - 1
                            label = parts[1].strip().lower()
                            if label in ("positive", "negative", "neutral") and idx < len(candidates):
                                candidates[idx]["sentiment"] = label
                        except (ValueError, IndexError):
                            pass
            logger.info("[Analyzer] Sentiment classified for %d items", len(candidates))
        except Exception as e:
            logger.warning("[Analyzer] Sentiment analysis failed: %s", e)

    def _sentiment_distribution(self, items: list) -> dict:
        dist = {}
        for item in items:
            s = item.get("sentiment") or "unknown"
            dist[s] = dist.get(s, 0) + 1
        return dist

    def _compute_trends(self, site_name: str, current_items: list) -> dict:
        if not self.store:
            return {}
        snapshots = self.store.get_all_snapshots(site_name)
        if len(snapshots) < 2:
            return {"status": "insufficient_data", "message": "Need at least 2 snapshots"}

        counts = [s["items_count"] for s in snapshots]
        timestamps = [s["timestamp"] for s in snapshots]

        recent_avg = sum(counts[-3:]) / min(3, len(counts[-3:]))
        older_avg = sum(counts[:max(1, len(counts) - 3)]) / max(1, len(counts) - 3)

        if recent_avg > older_avg * 1.1:
            direction = "up"
        elif recent_avg < older_avg * 0.9:
            direction = "down"
        else:
            direction = "stable"

        return {
            "direction": direction,
            "snapshot_counts": counts,
            "snapshot_times": timestamps,
            "recent_average": round(recent_avg, 1),
            "older_average": round(older_avg, 1),
        }
