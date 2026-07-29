# datarecon/infrastructure/persistence/sqlite_test_suite_repository.py
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.domain.interfaces.test_suite_repository import ITestSuiteRepository
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase

_COLUMNS = (
    "suite_id, project_id, name, module, description, config_json, "
    "source_connection_id, target_connection_id, schedule_cron, schedule_enabled, "
    "created_at, updated_at, last_run_id, last_run_status, last_run_at"
)


class SQLiteTestSuiteRepository(ITestSuiteRepository):
    def __init__(self, db: MetadataDatabase):
        self._db = db

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> TestSuite:
        return TestSuite(
            suite_id=row["suite_id"],
            project_id=row["project_id"],
            name=row["name"],
            module=ValidationModule(row["module"]),
            description=row["description"],
            config=json.loads(row["config_json"]),
            source_connection_id=row["source_connection_id"],
            target_connection_id=row["target_connection_id"],
            schedule_cron=row["schedule_cron"],
            schedule_enabled=bool(row["schedule_enabled"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_run_id=row["last_run_id"],
            last_run_status=(RunStatus(row["last_run_status"]) if row["last_run_status"] else None),
            last_run_at=(
                datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None
            ),
        )

    @staticmethod
    def _entity_to_params(s: TestSuite) -> tuple:
        return (
            s.suite_id,
            s.project_id,
            s.name,
            s.module.value,
            s.description,
            json.dumps(s.config, default=str),
            s.source_connection_id,
            s.target_connection_id,
            s.schedule_cron,
            int(s.schedule_enabled),
            s.created_at.isoformat(),
            s.updated_at.isoformat(),
            s.last_run_id,
            s.last_run_status.value if s.last_run_status else None,
            s.last_run_at.isoformat() if s.last_run_at else None,
        )

    def add(self, suite: TestSuite) -> TestSuite:
        placeholders = ", ".join(["?"] * 15)
        with self._db.cursor() as cur:
            cur.execute(
                f"INSERT INTO test_suites ({_COLUMNS}) VALUES ({placeholders})",
                self._entity_to_params(suite),
            )
        return suite

    def update(self, suite: TestSuite) -> TestSuite:
        suite.touch()
        with self._db.cursor() as cur:
            cur.execute(
                """
                UPDATE test_suites SET
                    project_id=?, name=?, module=?, description=?, config_json=?,
                    source_connection_id=?, target_connection_id=?, schedule_cron=?,
                    schedule_enabled=?, updated_at=?, last_run_id=?, last_run_status=?,
                    last_run_at=?
                WHERE suite_id=?
                """,
                (
                    suite.project_id,
                    suite.name,
                    suite.module.value,
                    suite.description,
                    json.dumps(suite.config, default=str),
                    suite.source_connection_id,
                    suite.target_connection_id,
                    suite.schedule_cron,
                    int(suite.schedule_enabled),
                    suite.updated_at.isoformat(),
                    suite.last_run_id,
                    suite.last_run_status.value if suite.last_run_status else None,
                    suite.last_run_at.isoformat() if suite.last_run_at else None,
                    suite.suite_id,
                ),
            )
        return suite

    def delete(self, suite_id: str) -> bool:
        with self._db.cursor() as cur:
            cur.execute("DELETE FROM test_suites WHERE suite_id=?", (suite_id,))
            return cur.rowcount > 0

    def get_by_id(self, suite_id: str) -> TestSuite | None:
        with self._db.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM test_suites WHERE suite_id=?", (suite_id,))
            row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def list_all(self) -> list[TestSuite]:
        with self._db.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM test_suites ORDER BY name")
            rows = cur.fetchall()
        return [self._row_to_entity(r) for r in rows]

    def list_by_project(self, project_id: str) -> list[TestSuite]:
        with self._db.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM test_suites WHERE project_id=? ORDER BY name",
                (project_id,),
            )
            rows = cur.fetchall()
        return [self._row_to_entity(r) for r in rows]

    def record_run_result(
        self, suite_id: str, run_id: str | None, status: RunStatus, when: datetime
    ) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE test_suites SET last_run_id=?, last_run_status=?, last_run_at=? "
                "WHERE suite_id=?",
                (run_id, status.value, when.isoformat(), suite_id),
            )
