"""Unit tests — ConnectionService (Module 1: CRUD, validation, connectivity test)."""

from __future__ import annotations

from pathlib import Path

import pytest

from datarecon.application.services.connection_service import ConnectionService
from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import ConnectionRole, DatabaseType, Environment
from datarecon.infrastructure.connectors.engine_factory import EngineFactory
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase
from datarecon.infrastructure.persistence.sqlite_connection_repository import (
    SQLiteConnectionRepository,
)
from datarecon.infrastructure.security.crypto import CredentialCipher


@pytest.fixture
def service(tmp_path: Path) -> ConnectionService:
    db = MetadataDatabase(tmp_path / "meta.db")
    cipher = CredentialCipher(tmp_path / "key.bin")
    repo = SQLiteConnectionRepository(db)
    return ConnectionService(repo, cipher, EngineFactory())


def _sqlite_conn(name: str = "conn-1", file_path: str = "/tmp/does-not-matter.db") -> Connection:
    return Connection(
        connection_name=name,
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.SQLITE,
        file_path=file_path,
    )


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def test_create_and_get_roundtrip(service: ConnectionService) -> None:
    created = service.create_connection(_sqlite_conn(), None)
    fetched = service.get_connection(created.connection_id)
    assert fetched is not None
    assert fetched.connection_name == "conn-1"
    assert fetched.database_type == DatabaseType.SQLITE


def test_get_connection_returns_none_for_unknown_id(service: ConnectionService) -> None:
    assert service.get_connection("does-not-exist") is None


def test_create_encrypts_password(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="pg-1",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.POSTGRESQL,
        host="db",
        database_name="d",
        username="u",
    )
    created = service.create_connection(conn, "s3cr3t")
    assert created.password_encrypted is not None
    assert created.password_encrypted != "s3cr3t"


def test_create_rejects_duplicate_name(service: ConnectionService) -> None:
    service.create_connection(_sqlite_conn("dup"), None)
    with pytest.raises(ValueError, match="already exists"):
        service.create_connection(_sqlite_conn("dup"), None)


def test_list_connections_returns_all(service: ConnectionService) -> None:
    service.create_connection(_sqlite_conn("a"), None)
    service.create_connection(_sqlite_conn("b"), None)
    names = {c.connection_name for c in service.list_connections()}
    assert names == {"a", "b"}


def test_update_without_password_preserves_existing_secret(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="pg-2",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.POSTGRESQL,
        host="db",
        database_name="d",
        username="u",
    )
    created = service.create_connection(conn, "original-secret")
    original_cipher = created.password_encrypted

    created.host = "new-host"
    updated = service.update_connection(created, None)

    assert updated.host == "new-host"
    assert updated.password_encrypted == original_cipher


def test_update_with_password_rotates_secret(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="pg-3",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.POSTGRESQL,
        host="db",
        database_name="d",
        username="u",
    )
    created = service.create_connection(conn, "original-secret")
    original_cipher = created.password_encrypted

    updated = service.update_connection(created, "rotated-secret")

    assert updated.password_encrypted != original_cipher


def test_delete_connection(service: ConnectionService) -> None:
    created = service.create_connection(_sqlite_conn(), None)
    assert service.delete_connection(created.connection_id) is True
    assert service.get_connection(created.connection_id) is None


def test_delete_unknown_connection_returns_false(service: ConnectionService) -> None:
    assert service.delete_connection("does-not-exist") is False


def test_clone_connection_copies_fields_and_resets_stats(service: ConnectionService) -> None:
    created = service.create_connection(_sqlite_conn("original"), None)
    clone = service.clone_connection(created.connection_id)

    assert clone.connection_id != created.connection_id
    assert clone.connection_name == "original (Copy)"
    assert clone.file_path == created.file_path
    assert clone.usage_count == 0
    assert clone.last_test_status is None
    assert service.get_connection(clone.connection_id) is not None


def test_clone_unknown_connection_raises(service: ConnectionService) -> None:
    with pytest.raises(ValueError, match="not found"):
        service.clone_connection("does-not-exist")


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_validate_requires_connection_name(service: ConnectionService) -> None:
    conn = _sqlite_conn()
    conn.connection_name = "   "
    with pytest.raises(ValueError, match="name is required"):
        service.create_connection(conn, None)


def test_validate_sqlite_requires_file_path(service: ConnectionService) -> None:
    conn = _sqlite_conn(file_path=None)
    with pytest.raises(ValueError, match="file path"):
        service.create_connection(conn, None)


def test_validate_snowflake_requires_account_and_username(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="sf",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.SNOWFLAKE,
    )
    with pytest.raises(ValueError, match="Snowflake"):
        service.create_connection(conn, None)


def test_validate_databricks_requires_host_and_http_path(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="db",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.DATABRICKS,
    )
    with pytest.raises(ValueError, match="Databricks"):
        service.create_connection(conn, None)


def test_validate_jdbc_requires_url_and_driver_class(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="jdbc",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.JDBC,
    )
    with pytest.raises(ValueError, match="JDBC"):
        service.create_connection(conn, None)


def test_validate_odbc_requires_driver(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="odbc",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.ODBC,
    )
    with pytest.raises(ValueError, match="ODBC"):
        service.create_connection(conn, None)


def test_validate_file_source_requires_path(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="csv",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
    )
    with pytest.raises(ValueError, match="file path"):
        service.create_connection(conn, None)


def test_validate_storage_requires_bucket(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="s3",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.AWS_S3,
    )
    with pytest.raises(ValueError, match="bucket"):
        service.create_connection(conn, None)


def test_validate_azure_storage_requires_storage_account(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="az",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.AZURE_BLOB,
        bucket="container",
    )
    with pytest.raises(ValueError, match="storage account"):
        service.create_connection(conn, None)


def test_validate_relational_requires_host_and_username(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="pg",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.POSTGRESQL,
    )
    with pytest.raises(ValueError, match="requires host and username"):
        service.create_connection(conn, None)


def test_validate_passes_for_well_formed_connection(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="ok",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.POSTGRESQL,
        host="db",
        username="u",
        environment=Environment.PROD,
    )
    created = service.create_connection(conn, "pw")
    assert created.connection_id


# --------------------------------------------------------------------------- #
# Connectivity test
# --------------------------------------------------------------------------- #
def test_test_connection_passes_for_existing_sqlite_file(
    service: ConnectionService, tmp_path: Path
) -> None:
    db_file = tmp_path / "source.db"
    db_file.write_text("")
    created = service.create_connection(_sqlite_conn(file_path=str(db_file)), None)

    result = service.test_connection(created.connection_id)

    assert result.success is True
    assert result.elapsed_ms >= 0
    fetched = service.get_connection(created.connection_id)
    assert fetched.last_test_status == "PASS"


def test_test_connection_fails_for_missing_file(service: ConnectionService) -> None:
    # SQLite is a SQLAlchemy-managed type (not the Module 1 "File Source"
    # category), so a missing file surfaces as a driver-level connect error
    # rather than the service's own FileNotFoundError pre-check.
    created = service.create_connection(
        _sqlite_conn(file_path="/nonexistent/path/should-not-exist.db"), None
    )

    result = service.test_connection(created.connection_id)

    assert result.success is False
    assert "unable to open database file" in result.message.lower()
    fetched = service.get_connection(created.connection_id)
    assert fetched.last_test_status == "FAIL"


def test_test_connection_fails_for_missing_csv_file(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="csv-missing",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
        file_path="/nonexistent/data.csv",
    )
    created = service.create_connection(conn, None)

    result = service.test_connection(created.connection_id)

    assert result.success is False
    assert "not found" in result.message.lower()


def test_test_connection_sanitizes_leaked_password_in_error(service: ConnectionService) -> None:
    conn = Connection(
        connection_name="odbc-leak",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.ODBC,
        driver="does-not-exist-driver",
    )
    created = service.create_connection(conn, "TopSecret123")

    result = service.test_connection(created.connection_id)

    assert result.success is False
    assert "TopSecret123" not in result.message


def test_test_connection_unknown_id_raises(service: ConnectionService) -> None:
    with pytest.raises(ValueError, match="not found"):
        service.test_connection("does-not-exist")


def test_sanitize_redacts_pwd_and_password_patterns() -> None:
    conn = _sqlite_conn()
    message = "connection failed: PWD=hunter2;UID=admin and password=another-secret"
    sanitized = ConnectionService._sanitize(message, conn)
    assert "hunter2" not in sanitized
    assert "another-secret" not in sanitized
    assert "PWD=***" in sanitized
    assert "password=***" in sanitized
