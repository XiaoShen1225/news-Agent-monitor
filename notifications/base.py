"""Abstract base class for notification channels."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PipelineEvent:
    site_name: str
    url: str
    status: str  # "success", "error", "skipped_no_change"
    items_count: int
    new_items: int
    removed_items: int
    modified_items: int
    trend_direction: str
    summary: str | None
    error: str | None
    timestamp: str
    alert_matches: list | None = None  # keyword alert matches
    anomalies: list | None = None  # volume spike/drop detections
    sentiment_shift: dict | None = None  # sentiment distribution shift
    story_matches: list | None = None  # story follow-up matches


class BaseNotifier(ABC):
    """Abstract notifier — all channels implement send()."""

    @abstractmethod
    async def send(self, event: PipelineEvent) -> bool:
        """Send a notification. Returns True on success."""
        ...

    def _format_message(self, event: PipelineEvent) -> str:
        """Build a human-readable notification message with optional alerts."""
        status_icon = {"success": "✅", "error": "❌", "skipped_no_change": "○"}
        icon = status_icon.get(event.status, "?")

        lines = [
            f"## {icon} News Monitor: {event.site_name}",
            "",
            f"- **Status**: {event.status}",
            f"- **Time**: {event.timestamp}",
            f"- **URL**: {event.url}",
        ]

        if event.status == "error":
            lines.append(f"- **Error**: {event.error}")
        elif event.status == "success":
            lines.append(
                f"- **Items**: {event.items_count} (new: {event.new_items}, "
                f"removed: {event.removed_items}, modified: {event.modified_items})"
            )
            lines.append(f"- **Trend**: {event.trend_direction}")
            if event.summary:
                lines.append("")
                lines.append(f"> {event.summary}")

            # ── Alert section ──────────────────────────────────────────
            alert_lines = self._format_alerts(event)
            if alert_lines:
                lines.append("")
                lines.append("---")
                lines.append("")
                lines.extend(alert_lines)

        return "\n".join(lines)

    def _format_alerts(self, event: PipelineEvent) -> list[str]:
        """Build alert-specific message lines. Override in subclasses for custom formatting."""
        lines = []

        if event.anomalies:
            lines.append("### ⚠️ 异常告警")
            for a in event.anomalies:
                atype = "📈 量级突增" if a["type"] == "volume_spike" else "📉 量级骤降"
                lines.append(
                    f"- {atype}: 当前 {a['current_count']} 条, "
                    f"基线均值 {a['baseline_avg']}, Z-score={a['zscore']}"
                )

        if event.alert_matches:
            lines.append("### 🔔 关键词匹配")
            for m in event.alert_matches:
                lines.append(f"- [{m['keyword']}] {m['title']}")
                if m.get("url"):
                    lines.append(f"  {m['url']}")

        if event.sentiment_shift and event.sentiment_shift.get("significant"):
            lines.append("### 💬 情感偏移")
            shifted = event.sentiment_shift.get("shifted", {})
            for polarity, s in shifted.items():
                label = "正面" if polarity == "positive" else "负面"
                direction_text = "上升" if s["delta"] > 0 else "下降"
                lines.append(
                    f"- {label}情感{direction_text}: {s['from']:.0%} → {s['to']:.0%} (Δ{s['delta']:+.0%})"
                )

        if event.story_matches:
            lines.append("### 📰 故事后续")
            for m in event.story_matches:
                lines.append(f"- 追踪「{m['story_title'][:40]}」")
                lines.append(f"  后续: {m['item_title'][:80]}")
                if m.get("item_url"):
                    lines.append(f"  {m['item_url']}")
                lines.append(
                    f"  来源: {m.get('site', '?')} | 相似度: {m.get('score', 0):.2f}"
                )

        return lines
