# datarecon/domain/interfaces/notifier.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Notification:
    """One message about a scheduled run, in a channel-neutral shape.

    `subject` is what a channel with a title shows (an email header, a Slack
    fallback line); `body` is plain text so every channel can render it without
    a template. Channel-specific formatting belongs in the adapter.
    """

    subject: str
    body: str
    #: True when this reports a failure, so a channel can style or route it.
    is_failure: bool = False


class INotifier(ABC):
    """Port for outbound notifications (email, webhook, …).

    A notifier must never raise: a scheduled run that succeeded is not a
    failure because the mail server was down, and a run that failed must not
    lose its recorded result to a second failure in the notification path.
    Adapters swallow their own transport errors and report them via `errors`.
    """

    @abstractmethod
    def send(self, notification: Notification) -> bool:
        """Deliver the notification. Returns True when it was sent."""

    @property
    def errors(self) -> list[str]:
        """Transport failures since construction, oldest first."""
        return []
