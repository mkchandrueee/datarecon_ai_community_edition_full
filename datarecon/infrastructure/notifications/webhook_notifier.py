# datarecon/infrastructure/notifications/webhook_notifier.py
from __future__ import annotations

import json
import urllib.error
import urllib.request

from datarecon.domain.interfaces.notifier import INotifier, Notification


class WebhookNotifier(INotifier):
    """Posts a JSON message to an incoming-webhook URL (Slack, Teams, or any
    endpoint that accepts a `text` field).

    `urllib` rather than `requests`: one POST of a small JSON body does not
    justify adding a dependency to a Community Edition install.
    """

    def __init__(self, url: str, timeout: int = 15):
        self._url = url
        self._timeout = timeout
        self._errors: list[str] = []

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def send(self, notification: Notification) -> bool:
        if not self._url:
            self._errors.append("No webhook URL configured.")
            return False

        payload = json.dumps(
            {"text": f"*{notification.subject}*\n{notification.body}"}
        ).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                if response.status >= 400:
                    self._errors.append(f"Webhook returned HTTP {response.status}.")
                    return False
        except Exception as exc:
            self._errors.append(f"Webhook notification failed: {exc}")
            return False
        return True
