# datarecon/infrastructure/notifications/composite_notifier.py
from __future__ import annotations

from collections.abc import Sequence

from datarecon.domain.interfaces.notifier import INotifier, Notification


class CompositeNotifier(INotifier):
    """Fans one notification out to every configured channel.

    Every channel is attempted even when an earlier one fails — an email
    outage should not also cost you the Slack message.
    """

    def __init__(self, notifiers: Sequence[INotifier]):
        self._notifiers = list(notifiers)

    @property
    def channels(self) -> list[INotifier]:
        return list(self._notifiers)

    @property
    def errors(self) -> list[str]:
        return [error for notifier in self._notifiers for error in notifier.errors]

    def send(self, notification: Notification) -> bool:
        results = [notifier.send(notification) for notifier in self._notifiers]
        return any(results)
