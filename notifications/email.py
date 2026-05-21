"""Email (SMTP) notification channel."""

import logging
from email.mime.text import MIMEText

import aiosmtplib

from .base import BaseNotifier, PipelineEvent

logger = logging.getLogger(__name__)


class EmailNotifier(BaseNotifier):
    """Send notifications via SMTP email.

    Config keys:
        smtp_host, smtp_port, smtp_user, smtp_password,
        from_addr, to_addrs (list), use_tls
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_addr: str = "",
        to_addrs: list = None,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_addr = from_addr or smtp_user
        self.to_addrs = to_addrs or []
        self.use_tls = use_tls

    async def send(self, event: PipelineEvent) -> bool:
        if event.status == "skipped_no_change":
            return True

        if not self.to_addrs:
            logger.warning("Email notifier has no recipients configured")
            return False

        body = self._format_message(event)
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[News Monitor] {event.site_name} — {event.status}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)

        try:
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user or None,
                password=self.smtp_password or None,
                start_tls=self.use_tls,
                timeout=15,
            )
            return True
        except Exception as e:
            logger.error("Email notify error: %s", e)
            return False
