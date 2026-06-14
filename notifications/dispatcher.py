"""Notifier dispatcher — loads channels from config and sends PipelineEvents."""

import hashlib
import logging
import time
from datetime import datetime, time as dtime
from typing import List

from .base import BaseNotifier, PipelineEvent, compute_priority
from .dingtalk import DingTalkNotifier
from .wecom import WeComNotifier
from .email import EmailNotifier

logger = logging.getLogger(__name__)

# ── In-memory dedup state (survives within a single process lifetime) ──
_dedup_cache: dict[str, float] = {}
_dedup_max = 500  # max entries before eviction


def _should_suppress(event: PipelineEvent, cooldown_minutes: int = 120) -> bool:
    """Check if a similar event was sent within the cooldown window."""
    key_raw = f"{event.site_name}|{event.status}|{event.priority}"
    key = hashlib.md5(key_raw.encode()).hexdigest()[:12]
    now = time.time()
    last = _dedup_cache.get(key)
    if last and (now - last) < cooldown_minutes * 60:
        return True
    _dedup_cache[key] = now
    # Evict oldest entries if cache grows too large
    if len(_dedup_cache) > _dedup_max:
        sorted_items = sorted(_dedup_cache.items(), key=lambda x: x[1])
        for old_key, _ in sorted_items[: len(_dedup_cache) // 2]:
            del _dedup_cache[old_key]
    return False


def _is_quiet_hours(quiet_start: str = "", quiet_end: str = "") -> bool:
    """Check if current time falls within quiet hours (e.g. 23:00-07:00)."""
    if not quiet_start or not quiet_end:
        return False
    try:
        now = datetime.now().time()
        start = dtime.fromisoformat(quiet_start + ":00")
        end = dtime.fromisoformat(quiet_end + ":00")
        if start < end:
            return start <= now < end
        else:  # overnight (e.g. 23:00-07:00)
            return now >= start or now < end
    except (ValueError, TypeError):
        return False


def create_notifiers(config: dict) -> List[BaseNotifier]:
    """Build a list of notifiers from the 'notifications' config section."""
    notifiers = []
    cfg = config.get("notifications", {}) or {}

    for entry in cfg.get("dingtalk", []) or []:
        if entry.get("webhook_url"):
            notifiers.append(
                DingTalkNotifier(
                    webhook_url=entry["webhook_url"],
                    secret=entry.get("secret", ""),
                )
            )
            logger.info("DingTalk notifier configured")

    for entry in cfg.get("wecom", []) or []:
        if entry.get("webhook_url"):
            notifiers.append(WeComNotifier(webhook_url=entry["webhook_url"]))
            logger.info("WeCom notifier configured")

    for entry in cfg.get("email", []) or []:
        if entry.get("smtp_host") and entry.get("to_addrs"):
            notifiers.append(
                EmailNotifier(
                    smtp_host=entry["smtp_host"],
                    smtp_port=entry.get("smtp_port", 587),
                    smtp_user=entry.get("smtp_user", ""),
                    smtp_password=entry.get("smtp_password", ""),
                    from_addr=entry.get("from_addr", ""),
                    to_addrs=entry["to_addrs"],
                    use_tls=entry.get("use_tls", True),
                )
            )
            logger.info("Email notifier configured: %s", entry["smtp_host"])

    # Telegram
    for entry in cfg.get("telegram", []) or []:
        if entry.get("bot_token") and entry.get("chat_id"):
            try:
                from .telegram import TelegramNotifier

                notifiers.append(
                    TelegramNotifier(
                        bot_token=entry["bot_token"],
                        chat_id=entry["chat_id"],
                    )
                )
                logger.info("Telegram notifier configured")
            except Exception as e:
                logger.warning("Failed to create Telegram notifier: %s", e)

    return notifiers


def build_event(result: dict, consecutive_failures: int = 0) -> PipelineEvent:
    """Build a PipelineEvent from a coordinator result dict."""
    report = result.get("report", {}) or {}
    status = result.get("status", "unknown")
    anomalies = result.get("anomalies") or []
    error = result.get("error")

    priority = compute_priority(
        status=status,
        error=error,
        anomalies=anomalies,
        consecutive_failures=consecutive_failures,
    )

    return PipelineEvent(
        site_name=result.get("site_name", "unknown"),
        url=result.get("url", ""),
        status=status,
        items_count=report.get("current_count", 0),
        new_items=len(report.get("new_items", [])),
        removed_items=len(report.get("removed_items", [])),
        modified_items=len(report.get("modified_items", [])),
        trend_direction=report.get("trends", {}).get("direction", "N/A"),
        summary=report.get("update_summary"),
        error=error,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        alert_matches=result.get("alert_matches") or [],
        anomalies=anomalies,
        sentiment_shift=result.get("sentiment_shift"),
        story_matches=result.get("story_matches") or [],
        priority=priority,
    )


async def notify_all(
    notifiers: List[BaseNotifier],
    event: PipelineEvent,
    quiet_start: str = "",
    quiet_end: str = "",
    cooldown_minutes: int = 120,
):
    """Send event to all notifiers with quiet-hours / dedup gating.

    - CRITICAL events bypass quiet hours and cooldown.
    - WARNING events obey cooldown but bypass quiet hours.
    - INFO events obey both quiet hours and cooldown.
    """
    if not notifiers:
        return

    # Skips with no changes are noise — only send if there are alert matches
    if event.status == "skipped_no_change" and not event.alert_matches:
        logger.debug("[Notify] Suppressed no-change skip for %s", event.site_name)
        return

    # INFO events respect quiet hours
    if event.priority == "INFO" and _is_quiet_hours(quiet_start, quiet_end):
        logger.debug("[Notify] Quiet hours — suppressed INFO for %s", event.site_name)
        return

    # Dedup check (CRITICAL always bypasses)
    if event.priority != "CRITICAL" and _should_suppress(event, cooldown_minutes):
        logger.debug("[Notify] Dedup suppressed for %s", event.site_name)
        return

    for n in notifiers:
        try:
            ok = await n.send(event)
            if not ok:
                logger.warning("Notifier %s returned failure", type(n).__name__)
        except Exception as e:
            logger.error("Notifier %s raised: %s", type(n).__name__, e)
