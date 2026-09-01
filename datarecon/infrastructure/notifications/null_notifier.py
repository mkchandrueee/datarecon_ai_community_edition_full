# datarecon/infrastructure/notifications/null_notifier.py
from __future__ import annotations

from datarecon.domain.interfaces.notifier import INotifier, Notification


class NullNotifier(INotifier):
    """Notifier for an installation with no channel configured.

    Scheduling works without notifications, so the absence of SMTP settings is
    a valid configuration rather than an error. Sent messages are kept so the
    UI can show what *would* have gone out.
    """

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> bool:
        self.sent.append(notification)
        return False
