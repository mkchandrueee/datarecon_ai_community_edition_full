# datarecon/infrastructure/persistence/sqlite_project_repository.py
from __future__ import annotations

import sqlite3
from datetime import datetime

from datarecon.domain.entities.project import Project
from datarecon.domain.interfaces.project_repository import IProjectRepository
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase

_COLUMNS = "project_id, name, description, created_at, updated_at"


class SQLiteProjectRepository(IProjectRepository):
    def __init__(self, db: MetadataDatabase):
        self._db = db

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> Project:
        return Project(
            project_id=row["project_id"],
            name=row["name"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def add(self, project: Project) -> Project:
        with self._db.cursor() as cur:
            cur.execute(
                f"INSERT INTO projects ({_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (
                    project.project_id,
                    project.name,
                    project.description,
                    project.created_at.isoformat(),
                    project.updated_at.isoformat(),
                ),
            )
        return project

    def update(self, project: Project) -> Project:
        project.touch()
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE projects SET name=?, description=?, updated_at=? WHERE project_id=?",
                (
                    project.name,
                    project.description,
                    project.updated_at.isoformat(),
                    project.project_id,
                ),
            )
        return project

    def delete(self, project_id: str) -> bool:
        with self._db.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
            return cur.rowcount > 0

    def get_by_id(self, project_id: str) -> Project | None:
        with self._db.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM projects WHERE project_id=?", (project_id,))
            row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def get_by_name(self, name: str) -> Project | None:
        with self._db.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM projects WHERE name=?", (name,))
            row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def list_all(self) -> list[Project]:
        with self._db.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM projects ORDER BY name")
            rows = cur.fetchall()
        return [self._row_to_entity(r) for r in rows]
