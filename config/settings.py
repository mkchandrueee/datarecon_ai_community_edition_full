# config/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    app_name: str = "DataRecon AI - Community Edition"
    app_version: str = "1.0.0"
    metadata_db_path: Path = field(default_factory=lambda: DATA_DIR / "datarecon_meta.db")
    run_detail_dir: Path = field(default_factory=lambda: DATA_DIR / "run_details")
    encryption_key_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("DATARECON_KEY_PATH", str(DATA_DIR / ".datarecon.key"))
        )
    )
    connect_timeout_seconds: int = int(os.getenv("DATARECON_CONNECT_TIMEOUT", "10"))
    max_records_supported: int = 5_000_000

    # ---- Scheduling (ADR-0014) ----
    #: Zone the cron expressions are read in. Cron means local time to the
    #: people who write it, so this is configurable; runs are still stored UTC.
    schedule_timezone: str = os.getenv("DATARECON_SCHEDULE_TZ", "UTC")
    #: Seconds between scheduler ticks. Cron's resolution is one minute, so
    #: ticking faster only re-checks the same minute.
    scheduler_interval_seconds: int = int(os.getenv("DATARECON_SCHEDULER_INTERVAL", "60"))
    #: "failure" (default) notifies only when a scheduled run fails or errors;
    #: "always" notifies on every scheduled run.
    notify_on: str = os.getenv("DATARECON_NOTIFY_ON", "failure").strip().casefold()

    # ---- Notification channels ----
    # Credentials are deployment configuration: they come from the environment
    # and are never written to the metadata database.
    smtp_host: str = os.getenv("DATARECON_SMTP_HOST", "")
    smtp_port: int = int(os.getenv("DATARECON_SMTP_PORT", "587"))
    smtp_username: str = os.getenv("DATARECON_SMTP_USER", "")
    smtp_password: str = os.getenv("DATARECON_SMTP_PASSWORD", "")
    smtp_use_tls: bool = os.getenv("DATARECON_SMTP_TLS", "true").strip().casefold() != "false"
    notify_email_from: str = os.getenv("DATARECON_NOTIFY_FROM", "")
    notify_email_to: str = os.getenv("DATARECON_NOTIFY_TO", "")
    notify_webhook_url: str = os.getenv("DATARECON_NOTIFY_WEBHOOK", "")

    @property
    def email_recipients(self) -> list[str]:
        return [address.strip() for address in self.notify_email_to.split(",") if address.strip()]

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.notify_email_from and self.email_recipients)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.notify_webhook_url)


settings = Settings()
