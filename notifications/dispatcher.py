"""Notifier dispatcher — loads channels from config and sends PipelineEvents."""

import logging
from datetime import datetime
from typing import List

from .base import BaseNotifier, PipelineEvent
from .dingtalk import DingTalkNotifier
from .wecom import WeComNotifier
from .email import EmailNotifier

logger = logging.getLogger(__name__)


def create_notifiers(config: dict) -> List[BaseNotifier]:
    """Build a list of notifiers from the 'notifications' config section.

    Example config:
        notifications:
          dingtalk:
            - webhook_url: "https://oapi.dingtalk.com/robot/send?access_token=xxx"
              secret: "SEC..."
          wecom:
            - webhook_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
          email:
            - smtp_host: "smtp.gmail.com"
              smtp_port: 587
              smtp_user: "user@gmail.com"
              smtp_password: "${SMTP_PASSWORD}"
              to_addrs: ["alerts@example.com"]
    """
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

    return notifiers


def build_event(result: dict) -> PipelineEvent:
    """Build a PipelineEvent from a coordinator result dict."""
    report = result.get("report", {}) or {}
    return PipelineEvent(
        site_name=result.get("site_name", "unknown"),
        url=result.get("url", ""),
        status=result.get("status", "unknown"),
        items_count=report.get("current_count", 0),
        new_items=len(report.get("new_items", [])),
        removed_items=len(report.get("removed_items", [])),
        modified_items=len(report.get("modified_items", [])),
        trend_direction=report.get("trends", {}).get("direction", "N/A"),
        summary=report.get("update_summary"),
        error=result.get("error"),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        alert_matches=result.get("alert_matches") or [],
        anomalies=result.get("anomalies") or [],
        sentiment_shift=result.get("sentiment_shift"),
    )


async def notify_all(notifiers: List[BaseNotifier], event: PipelineEvent):
    """Send event to all notifiers; log failures but never raise."""
    if not notifiers:
        return
    for n in notifiers:
        try:
            ok = await n.send(event)
            if not ok:
                logger.warning("Notifier %s returned failure", type(n).__name__)
        except Exception as e:
            logger.error("Notifier %s raised: %s", type(n).__name__, e)
