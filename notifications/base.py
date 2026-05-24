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


class BaseNotifier(ABC):
    """Abstract notifier — all channels implement send()."""

    @abstractmethod
    async def send(self, event: PipelineEvent) -> bool:
        """Send a notification. Returns True on success."""
        ...

    def _format_message(self, event: PipelineEvent) -> str:
        """Build a human-readable notification message."""
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

        return "\n".join(lines)
