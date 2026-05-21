"""DingTalk (钉钉) bot webhook notification channel."""

import base64
import hashlib
import hmac
import logging
import time
from urllib.parse import quote_plus

import httpx

from .base import BaseNotifier, PipelineEvent

logger = logging.getLogger(__name__)


class DingTalkNotifier(BaseNotifier):
    """Send notifications via DingTalk group bot webhook.

    Config keys:
        webhook_url: Full webhook URL (or base_url + access_token)
        secret: Optional HMAC signing secret
    """

    def __init__(self, webhook_url: str, secret: str = ""):
        self.webhook_url = webhook_url
        self.secret = secret

    def _sign(self) -> str:
        """Build signed URL with timestamp+sign if secret is set."""
        if not self.secret:
            return self.webhook_url

        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = quote_plus(base64.b64encode(hmac_code))

        sep = "&" if "?" in self.webhook_url else "?"
        return f"{self.webhook_url}{sep}timestamp={ts}&sign={sign}"

    async def send(self, event: PipelineEvent) -> bool:
        if event.status == "skipped_no_change":
            return True  # Don't notify on no-change

        content = self._format_message(event)
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": f"News Monitor: {event.site_name}", "text": content},
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self._sign(), json=payload)
                data = resp.json()
                if data.get("errcode") == 0:
                    return True
                logger.warning("DingTalk send failed: %s", data)
                return False
        except Exception as e:
            logger.error("DingTalk notify error: %s", e)
            return False
