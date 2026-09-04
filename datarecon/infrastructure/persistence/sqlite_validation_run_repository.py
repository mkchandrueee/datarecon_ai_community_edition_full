# datarecon/infrastructure/persistence/sqlite_validation_run_repository.py
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.domain.interfaces.validation_run_repository import (
    IValidationRunRepository,
)
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase

_COLUMNS = (
    "run_id, module, name, status, summary_json, source_connection_id, "
    "target_connection_id, error_message, runtime_seconds, project_id, suite_id, "
    "archived, started_at, finished_at"
)


class SQLiteValidationRunRepository(IValidationRunRepository):
    def __init__(self, db: MetadataDatabase):
        self._db = db

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> ValidationRun:
        return ValidationRun(
            run_id=row["run_id"],
            module=ValidationModule(row["module"]),
            name=row["name"],
            status=RunStatus(row["status"]),
            summary=json.loads(row["summary_json"]),
            source_connection_id=row["source_connection_id"],
            target_connection_id=row["target_connection_id"],
            error_message=row["error_message"],
            runtime_seconds=row["runtime_seconds"],
            project_id=row["project_id"],
            suite_id=row["suite_id"],
            archived=bool(row["archived"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]),
        )

    def add(self, run: ValidationRun) -> ValidationRun:
        placeholders = ", ".join(["?"] * 14)
        with self._db.cursor() as cur:
            cur.execute(
                f"INSERT INTO validation_runs ({_COLUMNS}) VALUES ({placeholders})",
                (
                    run.run_id,
                    run.module.value,
                    run.name,
                    run.status.value,
                    json.dumps(run.summary, default=str),
                    run.source_connection_id,
                    run.target_connection_id,
                    run.error_message,
                    run.runtime_seconds,
                    run.project_id,
                    run.suite_id,
                    int(run.archived),
                    run.started_at.isoformat(),
                    run.finished_at.isoformat(),
                ),
            )
        return run

    def get_by_id(self, run_id: str) -> ValidationRun | None:
        with self._db.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM validation_runs WHERE run_id=?", (run_id,))
            row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def list_recent(self, limit: int = 200) -> list[ValidationRun]:
        with self._db.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM validation_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [self._row_to_entity(r) for r in rows]

    def list_by_module(self, module: ValidationModule, limit: int = 200) -> list[ValidationRun]:
        with self._db.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM validation_runs WHERE module=? "
                "ORDER BY started_at DESC LIMIT ?",
                (module.value, limit),
            )
            rows = cur.fetchall()
        return [self._row_to_entity(r) for r in rows]

    def list_by_project(self, project_id: str, limit: int = 200) -> list[ValidationRun]:
        with self._db.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM validation_runs WHERE project_id=? "
                "ORDER BY started_at DESC LIMIT ?",
                (project_id, limit),
            )
            rows = cur.fetchall()
        return [self._row_to_entity(r) for r in rows]

    def set_archived(self, run_id: str, archived: bool) -> bool:
        """Archive or restore one run. Returns False if the run doesn't exist."""
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE validation_runs SET archived=? WHERE run_id=?",
                (int(archived), run_id),
            )
            return cur.rowcount > 0

    def delete(self, run_id: str) -> bool:
        """Permanently remove one run. Returns False if the run doesn't exist."""
        with self._db.cursor() as cur:
            cur.execute("DELETE FROM validation_runs WHERE run_id=?", (run_id,))
            return cur.rowcount > 0

    def list_filtered(
        self,
        project_id: str | None = None,
        module: ValidationModule | None = None,
        suite_id: str | None = None,
        limit: int = 200,
        include_archived: bool = False,
    ) -> list[ValidationRun]:
        clauses = []
        params: list[str] = []
        if project_id is not None:
            clauses.append("project_id=?")
            params.append(project_id)
        if module is not None:
            clauses.append("module=?")
            params.append(module.value)
        if suite_id is not None:
            clauses.append("suite_id=?")
            params.append(suite_id)
        if not include_archived:
            clauses.append("archived=0")
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        with self._db.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM validation_runs {where}"
                "ORDER BY started_at DESC LIMIT ?",
                (*params, limit),
            )
            rows = cur.fetchall()
        return [self._row_to_entity(r) for r in rows]
