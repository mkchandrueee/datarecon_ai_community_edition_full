# datarecon/infrastructure/persistence/sqlite_connection_repository.py
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import ConnectionRole, DatabaseType, Environment
from datarecon.domain.interfaces.connection_repository import IConnectionRepository
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase

_COLUMNS = (
    "connection_id, connection_name, connection_role, database_type, project, "
    "environment, host, port, database_name, schema_name, username, "
    "password_encrypted, account, warehouse, role, driver, file_path, "
    "created_at, updated_at, last_tested_at, last_test_status, usage_count"
)


class SQLiteConnectionRepository(IConnectionRepository):
    def __init__(self, db: MetadataDatabase):
        self._db = db

    # ---------- mapping ----------
    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> Connection:
        return Connection(
            connection_id=row["connection_id"],
            connection_name=row["connection_name"],
            connection_role=ConnectionRole(row["connection_role"]),
            database_type=DatabaseType(row["database_type"]),
            project=row["project"],
            environment=Environment(row["environment"]),
            host=row["host"],
            port=row["port"],
            database_name=row["database_name"],
            schema_name=row["schema_name"],
            username=row["username"],
            password_encrypted=row["password_encrypted"],
            account=row["account"],
            warehouse=row["warehouse"],
            role=row["role"],
            driver=row["driver"],
            file_path=row["file_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_tested_at=(
                datetime.fromisoformat(row["last_tested_at"]) if row["last_tested_at"] else None
            ),
            last_test_status=row["last_test_status"],
            usage_count=row["usage_count"],
        )

    @staticmethod
    def _entity_to_params(c: Connection) -> tuple:
        return (
            c.connection_id,
            c.connection_name,
            c.connection_role.value,
            c.database_type.value,
            c.project,
            c.environment.value,
            c.host,
            c.port,
            c.database_name,
            c.schema_name,
            c.username,
            c.password_encrypted,
            c.account,
            c.warehouse,
            c.role,
            c.driver,
            c.file_path,
            c.created_at.isoformat(),
            c.updated_at.isoformat(),
            c.last_tested_at.isoformat() if c.last_tested_at else None,
            c.last_test_status,
            c.usage_count,
        )

    # ---------- CRUD ----------
    def add(self, connection: Connection) -> Connection:
        placeholders = ", ".join(["?"] * 22)
        with self._db.cursor() as cur:
            cur.execute(
                f"INSERT INTO connections ({_COLUMNS}) VALUES ({placeholders})",
                self._entity_to_params(connection),
            )
        return connection

    def update(self, connection: Connection) -> Connection:
        connection.touch()
        with self._db.cursor() as cur:
            cur.execute(
                """
                UPDATE connections SET
                    connection_name=?, connection_role=?, database_type=?, project=?,
                    environment=?, host=?, port=?, database_name=?, schema_name=?,
                    username=?, password_encrypted=?, account=?, warehouse=?, role=?,
                    driver=?, file_path=?, updated_at=?
                WHERE connection_id=?
                """,
                (
                    connection.connection_name,
                    connection.connection_role.value,
                    connection.database_type.value,
                    connection.project,
                    connection.environment.value,
                    connection.host,
                    connection.port,
                    connection.database_name,
                    connection.schema_name,
                    connection.username,
                    connection.password_encrypted,
                    connection.account,
                    connection.warehouse,
                    connection.role,
                    connection.driver,
                    connection.file_path,
                    connection.updated_at.isoformat(),
                    connection.connection_id,
                ),
            )
        return connection

    def delete(self, connection_id: str) -> bool:
        with self._db.cursor() as cur:
            cur.execute("DELETE FROM connections WHERE connection_id=?", (connection_id,))
            return cur.rowcount > 0

    def get_by_id(self, connection_id: str) -> Connection | None:
        with self._db.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM connections WHERE connection_id=?", (connection_id,)
            )
            row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def get_by_name(self, connection_name: str) -> Connection | None:
        with self._db.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM connections WHERE connection_name=?", (connection_name,)
            )
            row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def list_all(self) -> list[Connection]:
        with self._db.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM connections ORDER BY connection_name")
            rows = cur.fetchall()
        return [self._row_to_entity(r) for r in rows]

    def increment_usage(self, connection_id: str) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE connections SET usage_count = usage_count + 1 WHERE connection_id=?",
                (connection_id,),
            )

    def record_test_result(self, connection_id: str, status: str) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE connections SET last_tested_at=?, last_test_status=? WHERE connection_id=?",
                (datetime.now(UTC).isoformat(), status, connection_id),
            )
