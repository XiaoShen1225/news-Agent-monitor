"""WeCom (企业微信) bot webhook notification channel."""

import logging

import httpx

from .base import BaseNotifier, PipelineEvent

logger = logging.getLogger(__name__)


class WeComNotifier(BaseNotifier):
    """Send notifications via WeCom group bot webhook.

    Config keys:
        webhook_url: Full webhook URL with key parameter
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, event: PipelineEvent) -> bool:
        if event.status == "skipped_no_change":
            return True

        content = self._format_message(event)
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self.webhook_url, json=payload)
                data = resp.json()
                if data.get("errcode") == 0:
                    return True
                logger.warning("WeCom send failed: %s", data)
                return False
        except Exception as e:
            logger.error("WeCom notify error: %s", e)
            return False
