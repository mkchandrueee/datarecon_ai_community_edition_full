# datarecon/domain/entities/connection.py  (MODIFIED — Module 1 field matrix)
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from datarecon.domain.enums import (
    ConnectionCategory,
    ConnectionRole,
    DatabaseType,
    Environment,
    category_of,
)


@dataclass
class Connection:
    """Domain entity. `password_encrypted` always holds ciphertext (DB password,
    storage secret key/SAS token, PAT, or service-account JSON). Plaintext
    credentials never persist beyond the service boundary."""

    connection_name: str
    connection_role: ConnectionRole
    database_type: DatabaseType
    project: str = "Default"
    environment: Environment = Environment.DEV

    # Network databases
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    schema_name: str | None = None
    username: str | None = None
    password_encrypted: str | None = None

    # Snowflake
    account: str | None = None
    warehouse: str | None = None
    role: str | None = None

    # ODBC / driver metadata (PRD: Driver Class, Driver Location, JDBC URL)
    driver: str | None = None  # ODBC driver name or DSN
    driver_class: str | None = None  # JDBC driver class
    driver_location: str | None = None  # JDBC driver jar path(s)
    jdbc_url: str | None = None

    # Databricks / Hive / Spark
    http_path: str | None = None
    catalog: str | None = None

    # Cloud storage
    bucket: str | None = None  # S3/GCS bucket, Azure container/filesystem
    region: str | None = None
    storage_account: str | None = None
    cloud_project: str | None = None  # GCP project

    # Files / object keys
    file_path: str | None = None  # local path or object key
    file_format: str | None = None  # FileFormat value

    # Escape hatch for driver-specific options (JSON)
    extra_options: str | None = None

    connection_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_tested_at: datetime | None = None
    last_test_status: str | None = None
    usage_count: int = 0

    @property
    def category(self) -> ConnectionCategory:
        return category_of(self.database_type)

    def options(self) -> dict[str, Any]:
        if not self.extra_options:
            return {}
        try:
            parsed = json.loads(self.extra_options)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)
