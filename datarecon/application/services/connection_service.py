# datarecon/application/services/connection_service.py
from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import ConnectionCategory, DatabaseType
from datarecon.domain.interfaces.connection_repository import IConnectionRepository
from datarecon.infrastructure.connectors.dbapi_connector import DBAPIConnectorFactory
from datarecon.infrastructure.connectors.engine_factory import EngineFactory
from datarecon.infrastructure.connectors.mongodb_connector import MongoDBConnector
from datarecon.infrastructure.connectors.storage_client_factory import (
    StorageClientFactory,
)
from datarecon.infrastructure.security.crypto import CredentialCipher

_SECRET_RE = re.compile(r"(?i)\b(pwd|password)=([^;,\s]*)")


@dataclass(frozen=True)
class TestResult:
    success: bool
    message: str
    elapsed_ms: int


class ConnectionService:
    def __init__(
        self,
        repository: IConnectionRepository,
        cipher: CredentialCipher,
        engine_factory: EngineFactory,
    ):
        self._repo = repository
        self._cipher = cipher
        self._factory = engine_factory

    # ---------- CRUD ----------
    def list_connections(self) -> list[Connection]:
        return self._repo.list_all()

    def get_connection(self, connection_id: str) -> Connection | None:
        return self._repo.get_by_id(connection_id)

    def create_connection(
        self, connection: Connection, plaintext_password: str | None = None
    ) -> Connection:
        self._validate(connection)
        if self._repo.get_by_name(connection.connection_name):
            raise ValueError(f"A connection named '{connection.connection_name}' already exists.")
        connection.password_encrypted = self._cipher.encrypt(plaintext_password)
        return self._repo.add(connection)

    def update_connection(
        self, connection: Connection, plaintext_password: str | None = None
    ) -> Connection:
        self._validate(connection)
        if plaintext_password:
            connection.password_encrypted = self._cipher.encrypt(plaintext_password)
        return self._repo.update(connection)

    def delete_connection(self, connection_id: str) -> bool:
        return self._repo.delete(connection_id)

    def clone_connection(self, connection_id: str) -> Connection:
        source = self._require(connection_id)
        clone = replace(
            source,
            connection_id=uuid4().hex,
            connection_name=f"{source.connection_name} (Copy)",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            last_tested_at=None,
            last_test_status=None,
            usage_count=0,
        )
        return self._repo.add(clone)

    # ---------- connectivity ----------
    def test_connection(self, connection_id: str) -> TestResult:
        conn = self._require(connection_id)
        secret = self._cipher.decrypt(conn.password_encrypted) or ""
        start = time.perf_counter()
        try:
            category = conn.category
            if category == ConnectionCategory.FILE:
                path = Path(conn.file_path or "")
                if not path.is_file():
                    raise FileNotFoundError(f"File not found: {conn.file_path}")
            elif category == ConnectionCategory.STORAGE:
                StorageClientFactory().test(conn, secret)
            elif category == ConnectionCategory.NOSQL:
                MongoDBConnector().test(conn, secret)
            elif category == ConnectionCategory.GENERIC or not self._factory.supports(
                conn.database_type
            ):
                DBAPIConnectorFactory().test(conn, secret)  # ODBC/JDBC/Informix/IDMS
            else:
                engine = self._factory.create(conn, secret)
                self._factory.test(engine, conn.database_type)
                engine.dispose()
            elapsed = int((time.perf_counter() - start) * 1000)
            self._repo.record_test_result(connection_id, "PASS")
            return TestResult(True, "Connectivity check passed.", elapsed)
        except Exception as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            self._repo.record_test_result(connection_id, "FAIL")
            return TestResult(False, self._sanitize(str(exc), conn), elapsed)

    # ---------- helpers ----------
    def _require(self, connection_id: str) -> Connection:
        conn = self._repo.get_by_id(connection_id)
        if conn is None:
            raise ValueError(f"Connection '{connection_id}' not found.")
        return conn

    @staticmethod
    def _sanitize(message: str, conn: Connection) -> str:
        return _SECRET_RE.sub(lambda m: f"{m.group(1)}=***", message)

    @staticmethod
    def _validate(conn: Connection) -> None:
        if not conn.connection_name or not conn.connection_name.strip():
            raise ValueError("Connection name is required.")
        category = conn.category
        t = conn.database_type

        if t == DatabaseType.SQLITE:
            if not conn.file_path:
                raise ValueError("SQLite requires a database file path.")
        elif t == DatabaseType.SNOWFLAKE:
            if not conn.account or not conn.username:
                raise ValueError("Snowflake requires account and username.")
        elif t == DatabaseType.DATABRICKS:
            if not conn.host or not conn.http_path:
                raise ValueError("Databricks requires host and HTTP path.")
        elif t == DatabaseType.JDBC or (t == DatabaseType.IDMS and conn.jdbc_url):
            if not conn.jdbc_url or not conn.driver_class:
                raise ValueError(f"{t.value} requires JDBC URL and driver class.")
        elif t in (DatabaseType.ODBC, DatabaseType.INFORMIX, DatabaseType.IDMS):
            if not conn.driver:
                raise ValueError(f"{t.value} requires an ODBC driver name or DSN.")
        elif category == ConnectionCategory.FILE:
            if not conn.file_path:
                raise ValueError(f"{t.value} source requires a file path.")
        elif category == ConnectionCategory.STORAGE:
            if not conn.bucket:
                raise ValueError(f"{t.value} requires a bucket/container name.")
            if (
                t in (DatabaseType.AZURE_BLOB, DatabaseType.AZURE_DATA_LAKE)
                and not conn.storage_account
            ):
                raise ValueError(f"{t.value} requires a storage account name.")
        elif category == ConnectionCategory.NOSQL:
            if not conn.host and not conn.options().get("uri"):
                raise ValueError("MongoDB requires a host or connection URI.")
        else:  # remaining network relational databases
            if not conn.host or not conn.username:
                raise ValueError(f"{t.value} requires host and username.")
