"""Tests for notification channels and dispatching."""

import pytest
from notifications.base import PipelineEvent, BaseNotifier
from notifications.dispatcher import build_event, create_notifiers


class FakeNotifier(BaseNotifier):
    """Captures the last event sent."""
    def __init__(self):
        self.last_event = None

    async def send(self, event: PipelineEvent) -> bool:
        self.last_event = event
        return True


def make_result(status="success", **kwargs):
    """Build a minimal coordinator result dict."""
    return {
        "site_name": "test_site",
        "url": "https://example.com",
        "status": status,
        "error": None if status != "error" else "Boom",
        "report": {
            "current_count": 10,
            "new_items": [{}] * 2,
            "removed_items": [{}],
            "modified_items": [{}] * 3,
            "trends": {"direction": "up"},
            "llm_summary": "Things are looking good.",
            "total_changes": 6,
        },
        **kwargs,
    }


class TestPipelineEvent:
    def test_build_event_success(self):
        e = build_event(make_result())
        assert e.status == "success"
        assert e.items_count == 10
        assert e.new_items == 2
        assert e.removed_items == 1
        assert e.modified_items == 3
        assert e.trend_direction == "up"
        assert e.summary == "Things are looking good."

    def test_build_event_error(self):
        e = build_event(make_result(status="error"))
        assert e.status == "error"
        assert e.error == "Boom"

    def test_build_event_empty_report(self):
        e = build_event(make_result(status="skipped_no_change", report=None))
        assert e.status == "skipped_no_change"
        assert e.items_count == 0

    def test_event_timestamp(self):
        e = build_event(make_result())
        assert e.timestamp
        assert ":" in e.timestamp


class TestFormatMessage:
    def test_success_message(self):
        n = FakeNotifier()
        e = build_event(make_result())
        msg = n._format_message(e)
        assert "test_site" in msg
        assert "success" in msg
        assert "10" in msg
        assert "Things are looking good" in msg

    def test_error_message(self):
        n = FakeNotifier()
        e = build_event(make_result(status="error"))
        msg = n._format_message(e)
        assert "error" in msg
        assert "Boom" in msg


class TestCreateNotifiers:
    def test_empty_config(self):
        notifiers = create_notifiers({})
        assert notifiers == []

    def test_dingtalk_created(self):
        config = {
            "notifications": {
                "dingtalk": [{"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=abc"}]
            }
        }
        notifiers = create_notifiers(config)
        assert len(notifiers) == 1
        assert "DingTalk" in type(notifiers[0]).__name__

    def test_wecom_created(self):
        config = {
            "notifications": {
                "wecom": [{"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"}]
            }
        }
        notifiers = create_notifiers(config)
        assert len(notifiers) == 1
        assert "WeCom" in type(notifiers[0]).__name__

    def test_email_created(self):
        config = {
            "notifications": {
                "email": [{
                    "smtp_host": "smtp.example.com",
                    "smtp_port": 587,
                    "smtp_user": "u",
                    "smtp_password": "p",
                    "to_addrs": ["a@b.com"],
                }]
            }
        }
        notifiers = create_notifiers(config)
        assert len(notifiers) == 1
        assert "Email" in type(notifiers[0]).__name__

    def test_email_skipped_without_host(self):
        config = {
            "notifications": {
                "email": [{"smtp_host": "", "to_addrs": ["a@b.com"]}]
            }
        }
        notifiers = create_notifiers(config)
        assert notifiers == []

    def test_email_skipped_without_recipients(self):
        config = {
            "notifications": {
                "email": [{"smtp_host": "smtp.example.com", "to_addrs": []}]
            }
        }
        notifiers = create_notifiers(config)
        assert notifiers == []

    def test_multiple_channels(self):
        config = {
            "notifications": {
                "dingtalk": [{"webhook_url": "https://x.com"}],
                "wecom": [{"webhook_url": "https://y.com"}],
            }
        }
        notifiers = create_notifiers(config)
        assert len(notifiers) == 2

    def test_dingtalk_skipped_without_url(self):
        notifiers = create_notifiers({"notifications": {"dingtalk": [{"webhook_url": ""}]}})
        assert notifiers == []
