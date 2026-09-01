"""Unit tests — notification adapters (ADR-0014).

The governing rule is that a notifier never raises: the run result is already
recorded by the time one is called, and losing it to a mail-server outage would
be the worse failure.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from datarecon.domain.interfaces.notifier import INotifier, Notification
from datarecon.infrastructure.notifications import (
    CompositeNotifier,
    EmailNotifier,
    NullNotifier,
    WebhookNotifier,
)
from datarecon.infrastructure.notifications.factory import build_notifier


@pytest.fixture
def message() -> Notification:
    return Notification(subject="DataRecon: 1 suite failed", body="RC_ORDERS failed", is_failure=True)


class Stub(INotifier):
    def __init__(self, result: bool):
        self.result = result
        self.calls = 0

    def send(self, notification: Notification) -> bool:
        self.calls += 1
        return self.result


# ---------- null ----------


def test_null_notifier_reports_not_sent_but_records_the_message(message) -> None:
    notifier = NullNotifier()

    assert notifier.send(message) is False
    assert notifier.sent == [message]


# ---------- composite ----------


def test_composite_sends_to_every_channel(message) -> None:
    a, b = Stub(True), Stub(True)

    assert CompositeNotifier([a, b]).send(message) is True
    assert (a.calls, b.calls) == (1, 1)


def test_composite_still_tries_later_channels_after_one_fails(message) -> None:
    """An email outage should not also cost you the Slack message."""
    failing, working = Stub(False), Stub(True)

    assert CompositeNotifier([failing, working]).send(message) is True
    assert working.calls == 1


def test_composite_reports_failure_only_when_every_channel_failed(message) -> None:
    assert CompositeNotifier([Stub(False), Stub(False)]).send(message) is False


def test_composite_with_no_channels_reports_failure(message) -> None:
    assert CompositeNotifier([]).send(message) is False


# ---------- email ----------


def test_email_without_recipients_fails_rather_than_raising(message) -> None:
    notifier = EmailNotifier(host="localhost", port=25, sender="a@b.c", recipients=[])

    assert notifier.send(message) is False
    assert "recipients" in notifier.errors[0]


def test_email_swallows_a_dead_smtp_server(message) -> None:
    # Port 1 is reserved and refuses connections, so this exercises the real
    # failure path rather than a mocked one.
    notifier = EmailNotifier(
        host="127.0.0.1", port=1, sender="a@b.c", recipients=["x@y.z"], timeout=1
    )

    assert notifier.send(message) is False
    assert notifier.errors and "Email notification failed" in notifier.errors[0]


def test_email_builds_a_message_with_subject_and_recipients(message, monkeypatch) -> None:
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            captured["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def starttls(self):
            captured["tls"] = True

        def login(self, user, password):
            captured["user"] = user

        def send_message(self, msg):
            captured["subject"] = msg["Subject"]
            captured["to"] = msg["To"]
            captured["body"] = msg.get_content()

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    notifier = EmailNotifier(
        host="mail.example.com",
        port=587,
        sender="datarecon@example.com",
        recipients=["a@example.com", "b@example.com"],
        username="datarecon",
        password="secret",
    )

    assert notifier.send(message) is True
    assert captured["subject"] == message.subject
    assert captured["to"] == "a@example.com, b@example.com"
    assert message.body in captured["body"]
    assert captured["tls"] is True


# ---------- webhook ----------


def test_webhook_without_a_url_fails_rather_than_raising(message) -> None:
    notifier = WebhookNotifier("")

    assert notifier.send(message) is False
    assert "webhook URL" in notifier.errors[0]


def test_webhook_swallows_an_unreachable_endpoint(message) -> None:
    notifier = WebhookNotifier("http://127.0.0.1:1/hook", timeout=1)

    assert notifier.send(message) is False
    assert notifier.errors and "Webhook notification failed" in notifier.errors[0]


def test_webhook_posts_the_subject_and_body_as_json(message, monkeypatch) -> None:
    import json

    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["content_type"] = request.headers.get("Content-type")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert WebhookNotifier("https://hooks.example.com/x").send(message) is True
    assert captured["url"] == "https://hooks.example.com/x"
    assert message.subject in captured["payload"]["text"]
    assert message.body in captured["payload"]["text"]
    assert captured["content_type"] == "application/json"


def test_webhook_treats_an_error_status_as_a_failure(message, monkeypatch) -> None:
    class FakeResponse:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResponse())

    notifier = WebhookNotifier("https://hooks.example.com/x")
    assert notifier.send(message) is False
    assert "HTTP 500" in notifier.errors[0]


# ---------- factory ----------


@dataclass
class FakeSettings:
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    notify_email_from: str = ""
    notify_email_to: str = ""
    notify_webhook_url: str = ""

    @property
    def email_recipients(self) -> list[str]:
        return [a.strip() for a in self.notify_email_to.split(",") if a.strip()]

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.notify_email_from and self.email_recipients)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.notify_webhook_url)


def test_no_configuration_yields_a_null_notifier() -> None:
    """An install with no channel is valid — scheduling still works."""
    assert isinstance(build_notifier(FakeSettings()), NullNotifier)


def test_email_settings_yield_an_email_channel() -> None:
    notifier = build_notifier(
        FakeSettings(
            smtp_host="mail.example.com",
            notify_email_from="a@b.c",
            notify_email_to="x@y.z",
        )
    )
    assert isinstance(notifier, CompositeNotifier)
    assert [type(c) for c in notifier.channels] == [EmailNotifier]


def test_both_channels_are_wired_when_both_are_configured() -> None:
    notifier = build_notifier(
        FakeSettings(
            smtp_host="mail.example.com",
            notify_email_from="a@b.c",
            notify_email_to="x@y.z",
            notify_webhook_url="https://hooks.example.com/x",
        )
    )
    assert [type(c) for c in notifier.channels] == [EmailNotifier, WebhookNotifier]


def test_incomplete_email_settings_are_not_treated_as_configured() -> None:
    """A host with no recipients would fail on every send; leave it off."""
    notifier = build_notifier(FakeSettings(smtp_host="mail.example.com"))
    assert isinstance(notifier, NullNotifier)
