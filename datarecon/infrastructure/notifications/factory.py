# datarecon/infrastructure/notifications/factory.py
from __future__ import annotations

from typing import Any

from datarecon.domain.interfaces.notifier import INotifier
from datarecon.infrastructure.notifications.composite_notifier import CompositeNotifier
from datarecon.infrastructure.notifications.email_notifier import EmailNotifier
from datarecon.infrastructure.notifications.null_notifier import NullNotifier
from datarecon.infrastructure.notifications.webhook_notifier import WebhookNotifier


def build_notifier(settings: Any) -> INotifier:
    """Assemble whichever notification channels the environment has configured.

    No channel configured is a valid installation, not an error — scheduling
    still works, the runs are still recorded, and nobody gets mail.
    """
    channels: list[INotifier] = []
    if settings.email_configured:
        channels.append(
            EmailNotifier(
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=settings.notify_email_from,
                recipients=settings.email_recipients,
                username=settings.smtp_username or None,
                password=settings.smtp_password or None,
                use_tls=settings.smtp_use_tls,
            )
        )
    if settings.webhook_configured:
        channels.append(WebhookNotifier(settings.notify_webhook_url))
    return CompositeNotifier(channels) if channels else NullNotifier()
