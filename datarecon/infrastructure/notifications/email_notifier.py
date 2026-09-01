# datarecon/infrastructure/notifications/email_notifier.py
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from datarecon.domain.interfaces.notifier import INotifier, Notification


class EmailNotifier(INotifier):
    """SMTP email, using only the standard library.

    Credentials come from the environment (see `config/settings.py`), never
    from the metadata database: a scheduled job's mail password is deployment
    configuration, not application data, and does not belong in a file users
    copy between machines.
    """

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        recipients: list[str],
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        timeout: int = 15,
    ):
        self._host = host
        self._port = port
        self._sender = sender
        self._recipients = [r for r in recipients if r]
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout
        self._errors: list[str] = []

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def send(self, notification: Notification) -> bool:
        if not self._recipients:
            self._errors.append("No email recipients configured.")
            return False

        message = EmailMessage()
        message["Subject"] = notification.subject
        message["From"] = self._sender
        message["To"] = ", ".join(self._recipients)
        message.set_content(notification.body)

        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
                if self._use_tls:
                    smtp.starttls()
                if self._username:
                    smtp.login(self._username, self._password or "")
                smtp.send_message(message)
        except Exception as exc:
            # A notifier never raises: the run result is already recorded, and
            # losing it to a mail-server outage would be the worse failure.
            self._errors.append(f"Email notification failed: {exc}")
            return False
        return True
