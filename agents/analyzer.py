"""AnalyzerAgent: compare snapshots, detect changes, compute trends, detect anomalies, sentiment shift."""

import asyncio
import logging
import statistics
from datetime import datetime

from data.utils import title_similar

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

    async def run_async(
        self,
        current_items: list,
        site_name: str,
        content_hash: str,
        store=None,
        watch_context: dict = None,
        preference_context: str = "",
    ) -> dict:
        """Compare current items with previous snapshot.

        ``watch_context`` and ``preference_context`` are optional personalization
        data from the coordinator — injected into the update summary prompt.
        """
        logger.info(
            "[Analyzer] Analyzing %d items for %s", len(current_items), site_name
        )

        _store = store or self.store
        previous = _store.get_last_snapshot(site_name) if _store else None
        prev_items = previous.get("items", []) if previous else []

        new_items, removed_items, modified_items = self._diff_items(
            prev_items, current_items
        )

        total_changes = len(new_items) + len(removed_items) + len(modified_items)

        snapshots = _store.get_snapshot_meta_list(site_name) if _store else []

        trends = self._compute_trends(current_items, snapshots)

        sentiment_dist = self._compute_sentiment_distribution(current_items)
        sentiment_shift = self._compute_sentiment_shift(sentiment_dist, prev_items)

        anomalies = self._detect_anomalies(current_items, snapshots)

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
            "sentiment_shift": sentiment_shift,
            "anomalies": anomalies,
        }

        report["update_summary"] = await self._generate_update_summary_async(
            report, watch_context, preference_context
        )

        logger.info(
            "[Analyzer] Changes: %d new, %d removed, %d modified",
            len(new_items),
            len(removed_items),
            len(modified_items),
        )

        return report

    async def _generate_update_summary_async(
        self,
        report: dict,
        watch_context: dict = None,
        preference_context: str = "",
    ) -> str | None:
        """Generate an update summary, prioritizing user interests when available."""
        site_label = report.get("site_name", "未知站点")
        is_first = report.get("is_first_run", False)
        total_count = report.get("current_count", 0)

        if is_first or total_count == 0:
            return None

        new_count = len(report.get("new_items", []))
        removed_count = len(report.get("removed_items", []))
        tag_dist = report.get("tag_distribution", {})
        top_tags = list(tag_dist.items())[:5]
        direction = report.get("trends", {}).get("direction", "stable")

        if new_count == 0 and removed_count == 0:
            return f"「{site_label}」本次无新增内容，共 {total_count} 条。趋势：{direction}。"

        # ── Build personalized context sections ──
        watch_ctx = watch_context or {}
        watch_topics = watch_ctx.get("active_topics", [])
        matched_items = watch_ctx.get("matched_items", [])

        interest_section = ""
        if preference_context:
            interest_section = f"\n用户兴趣画像：\n{preference_context}\n"

        watch_section = ""
        if watch_topics:
            topic_names = [t["title"] for t in watch_topics[:10]]
            watch_section = f"\n用户关注主题：{topic_names}\n"
        if matched_items:
            match_lines = [
                f"  - [{m['watch_title']}] {m['item_title']}" for m in matched_items[:8]
            ]
            watch_section += (
                f"\n匹配用户关注的条目（共 {len(matched_items)} 条）：\n"
                + "\n".join(match_lines)
            )

        # Build prompt with new/removed item samples
        new_titles = [it.get("title", "") for it in report.get("new_items", [])[:10]]
        removed_titles = [
            it.get("title", "") for it in report.get("removed_items", [])[:5]
        ]

        # For article sources, include summaries
        article_samples = ""
        for it in report.get("new_items", [])[:3]:
            s = it.get("summary", "")
            if s:
                article_samples += f"\n  [{it.get('title', '')[:60]}] {s[:120]}"

        user_prompt = f"""站点「{site_label}」本次抓取结果：

共 {total_count} 条内容（新增 {new_count}，移除 {removed_count}）
趋势方向：{direction}
标签分布 Top 5：{top_tags}
{interest_section}{watch_section}
新增内容示例：{new_titles}
移除内容示例：{removed_titles}{article_samples}

请用 2-3 句中文简洁总结本次更新。如果提供了用户兴趣和关注主题，优先突出与用户相关的内容变化，不要简单罗列数字。控制在 80 字以内。"""

        try:
            summary = await self.call_llm_async(
                system_prompt=(
                    "你是一个内容更新分析助手。请根据提供的数据用简洁中文总结本次更新。"
                    "如果提供了用户兴趣画像和关注主题，优先总结与用户兴趣相关的内容变化，"
                    "自然融入，不要生硬引用'用户画像'等词汇。控制在80字以内。"
                ),
                user_prompt=user_prompt,
                max_tokens=200,
                temperature=0.3,
                fallback=None,
            )
            if summary:
                logger.info("[Analyzer] Update summary: %s", summary[:80])
            return summary
        except Exception as e:
            logger.warning("[Analyzer] Update summary generation failed: %s", e)
            return None

    def _diff_items(self, prev: list, curr: list) -> tuple:
        prev_titles = {item.get("title", ""): item for item in prev}
        curr_titles = {item.get("title", ""): item for item in curr}
        prev_keys = set(prev_titles)
        curr_keys = set(curr_titles)

        new_items: list[dict] = []
        removed_items: list[dict] = []
        modified_items: list[dict] = []

        # -- exact matches --
        matched_prev: set[str] = set()
        matched_curr: set[str] = set()

        # -- fuzzy-match unmatched titles to catch truncation / minor edits --
        unmatched_new = [t for t in curr_keys if t and t not in prev_keys]
        unmatched_rem = [t for t in prev_keys if t and t not in curr_keys]
        for ct in unmatched_new:
            for pt in unmatched_rem:
                if pt in matched_prev:
                    continue
                if title_similar(ct, pt):
                    matched_prev.add(pt)
                    matched_curr.add(ct)
                    prev_item = prev_titles[pt]
                    curr_item = curr_titles[ct]
                    modified_items.append(
                        {
                            "title": ct,
                            "previous": prev_item,
                            "current": curr_item,
                            "fuzzy_matched": True,
                        }
                    )
                    break

        # -- true new items --
        for t in curr_keys:
            if t and t not in prev_keys and t not in matched_curr:
                new_items.append({"title": t, **curr_titles[t]})

        # -- true removed items --
        for t in prev_keys:
            if t and t not in curr_keys and t not in matched_prev:
                removed_items.append({"title": t, **prev_titles[t]})

        # -- modifications among exact-matched items --
        for t in curr_keys & prev_keys:
            if t:
                prev_item = prev_titles[t]
                curr_item = curr_titles[t]
                if prev_item.get("summary") != curr_item.get(
                    "summary"
                ) or prev_item.get("tag") != curr_item.get("tag"):
                    modified_items.append(
                        {
                            "title": t,
                            "previous": prev_item,
                            "current": curr_item,
                        }
                    )

        return new_items, removed_items, modified_items

    def _tag_distribution(self, items: list) -> dict:
        dist = {}
        for item in items:
            tag = item.get("tag", "其他") or "其他"
            dist[tag] = dist.get(tag, 0) + 1
        return dict(sorted(dist.items(), key=lambda x: x[1], reverse=True))

    def _compute_trends(self, current_items: list, snapshots: list) -> dict:
        if len(snapshots) < 2:
            return {
                "status": "insufficient_data",
                "message": "Need at least 2 snapshots",
            }

        counts = [s["items_count"] for s in snapshots]
        timestamps = [s["timestamp"] for s in snapshots]

        recent_avg = sum(counts[-3:]) / min(3, len(counts[-3:]))
        older_avg = sum(counts[: max(1, len(counts) - 3)]) / max(1, len(counts) - 3)

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

    # ── anomaly detection ──────────────────────────────────────────────

    def _detect_anomalies(self, current_items: list, snapshots: list) -> list[dict]:
        """Detect volume spikes/drops using Z-score against recent snapshots."""
        if len(snapshots) < 5:
            return []

        counts = [
            s["items_count"] for s in snapshots[-11:-1]
        ]  # last 10, excluding current
        if len(counts) < 5:
            return []

        current_count = len(current_items)
        mean = statistics.mean(counts)
        stdev = statistics.stdev(counts) if len(counts) >= 2 else 0

        anomalies = []
        if stdev > 0:
            zscore = (current_count - mean) / stdev
            if zscore > 2.5:
                anomalies.append(
                    {
                        "type": "volume_spike",
                        "severity": round(min(zscore / 5.0, 1.0), 2),
                        "current_count": current_count,
                        "baseline_avg": round(mean, 1),
                        "zscore": round(zscore, 2),
                    }
                )
            elif zscore < -2.0 and current_count < 3:
                anomalies.append(
                    {
                        "type": "volume_drop",
                        "severity": round(min(abs(zscore) / 5.0, 1.0), 2),
                        "current_count": current_count,
                        "baseline_avg": round(mean, 1),
                        "zscore": round(zscore, 2),
                    }
                )

        if anomalies:
            logger.info("[Analyzer] Anomalies detected: %s", anomalies)
        return anomalies

    # ── sentiment analysis ──────────────────────────────────────────────

    def _compute_sentiment_distribution(self, items: list) -> dict:
        """Count positive/negative/neutral items based on item.sentiment field."""
        dist = {"positive": 0, "negative": 0, "neutral": 0}
        for item in items:
            s = item.get("sentiment", "") or ""
            dist[s] = dist.get(s, 0) + 1 if s in dist else dist.get("neutral", 0) + 1
        total = len(items) or 1
        return {
            "positive": dist["positive"],
            "negative": dist["negative"],
            "neutral": dist["neutral"],
            "positive_pct": round(dist["positive"] / total, 2),
            "negative_pct": round(dist["negative"] / total, 2),
            "neutral_pct": round(dist["neutral"] / total, 2),
        }

    def _compute_sentiment_shift(
        self, current_dist: dict, prev_items: list
    ) -> dict | None:
        """Compare current sentiment distribution with previous snapshot."""
        if not current_dist or not prev_items:
            return None
        prev_dist = {"positive": 0, "negative": 0, "neutral": 0}
        for item in prev_items:
            s = item.get("sentiment", "") or ""
            prev_dist[s] = (
                prev_dist.get(s, 0) + 1
                if s in prev_dist
                else prev_dist.get("neutral", 0) + 1
            )
        prev_total = len(prev_items) or 1

        shift = {}
        for key in ("positive", "negative"):
            curr_pct = current_dist.get(f"{key}_pct", 0)
            prev_pct = prev_dist[key] / prev_total
            delta = curr_pct - prev_pct
            if abs(delta) > 0.3:
                shift[key] = {
                    "from": round(prev_pct, 2),
                    "to": round(curr_pct, 2),
                    "delta": round(delta, 2),
                }

        if shift:
            return {"shifted": shift, "significant": True}
        return {"shifted": {}, "significant": False}
