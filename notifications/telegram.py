"""Telegram Bot notifier — sends PipelineEvents via Telegram Bot API."""

import logging
from .base import BaseNotifier, PipelineEvent

logger = logging.getLogger(__name__)


class TelegramNotifier(BaseNotifier):
    """Send notifications to a Telegram chat via bot."""

    def __init__(self, bot_token: str, chat_id: str | int):
        self._token = bot_token
        self._chat_id = str(chat_id)
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=f"https://api.telegram.org/bot{self._token}/",
                timeout=15.0,
            )
        return self._client

    async def send(self, event: PipelineEvent) -> bool:
        """Send notification via Telegram sendMessage API."""
        text = self._format_message(event)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            client = self._get_client()
            resp = await client.post("sendMessage", json=payload)
            if resp.status_code == 429:
                # Retry after specified delay
                import asyncio

                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning("[Telegram] Rate limited, retrying in %ds", retry_after)
                await asyncio.sleep(retry_after)
                resp2 = await client.post("sendMessage", json=payload)
                if resp2.status_code != 200:
                    logger.warning("[Telegram] send failed: %s", resp2.text[:200])
                    return False
            elif resp.status_code != 200:
                logger.warning("[Telegram] send failed: %s", resp.text[:200])
                return False
            logger.info("[Telegram] Sent notification for %s", event.site_name)
            return True
        except Exception as e:
            logger.warning("[Telegram] send error: %s", e)
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
