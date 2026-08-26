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


settings = Settings()
