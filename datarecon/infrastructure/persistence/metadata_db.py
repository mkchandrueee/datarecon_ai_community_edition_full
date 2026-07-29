# datarecon/infrastructure/persistence/metadata_db.py
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    connection_id       TEXT PRIMARY KEY,
    connection_name     TEXT NOT NULL UNIQUE,
    connection_role     TEXT NOT NULL,
    database_type       TEXT NOT NULL,
    project             TEXT NOT NULL DEFAULT 'Default',
    environment         TEXT NOT NULL DEFAULT 'DEV',
    host                TEXT,
    port                INTEGER,
    database_name       TEXT,
    schema_name         TEXT,
    username            TEXT,
    password_encrypted  TEXT,
    account             TEXT,
    warehouse           TEXT,
    role                TEXT,
    driver              TEXT,
    driver_class        TEXT,
    driver_location     TEXT,
    jdbc_url            TEXT,
    http_path           TEXT,
    catalog             TEXT,
    bucket              TEXT,
    region              TEXT,
    storage_account     TEXT,
    cloud_project       TEXT,
    file_path           TEXT,
    file_format         TEXT,
    extra_options       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    last_tested_at      TEXT,
    last_test_status    TEXT,
    usage_count         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS validation_runs (
    run_id                  TEXT PRIMARY KEY,
    module                  TEXT NOT NULL,
    name                    TEXT NOT NULL,
    status                  TEXT NOT NULL,
    summary_json            TEXT NOT NULL,
    source_connection_id    TEXT,
    target_connection_id    TEXT,
    error_message           TEXT,
    runtime_seconds         REAL NOT NULL DEFAULT 0,
    project_id              TEXT NOT NULL DEFAULT 'default',
    suite_id                TEXT,
    started_at              TEXT NOT NULL,
    finished_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_validation_runs_module ON validation_runs(module);
CREATE INDEX IF NOT EXISTS idx_validation_runs_started_at ON validation_runs(started_at);

CREATE TABLE IF NOT EXISTS projects (
    project_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

INSERT OR IGNORE INTO projects (project_id, name, description, created_at, updated_at)
VALUES (
    'default', 'Default', 'Default project for ungrouped test suites',
    datetime('now'), datetime('now')
);

CREATE TABLE IF NOT EXISTS test_suites (
    suite_id                TEXT PRIMARY KEY,
    project_id              TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    name                    TEXT NOT NULL,
    module                  TEXT NOT NULL,
    description             TEXT NOT NULL DEFAULT '',
    config_json             TEXT NOT NULL,
    source_connection_id    TEXT,
    target_connection_id    TEXT,
    schedule_cron           TEXT,
    schedule_enabled        INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    last_run_id             TEXT,
    last_run_status         TEXT,
    last_run_at             TEXT,
    UNIQUE(project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_test_suites_project ON test_suites(project_id);
CREATE INDEX IF NOT EXISTS idx_test_suites_module ON test_suites(module);
"""


class MetadataDatabase:
    """Owns the SQLite connection lifecycle and schema for connection metadata."""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(_SCHEMA)
        self._connection.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a database's first creation (SQLite has
        no schema-diffing `CREATE TABLE IF NOT EXISTS` equivalent for columns)."""
        columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(validation_runs)")
        }
        if "project_id" not in columns:
            self._connection.execute(
                "ALTER TABLE validation_runs ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default'"
            )
            self._connection.commit()
        if "suite_id" not in columns:
            self._connection.execute("ALTER TABLE validation_runs ADD COLUMN suite_id TEXT")
            self._connection.commit()
        # Column is guaranteed to exist at this point (either from CREATE TABLE
        # on a fresh DB, or from the ALTER TABLE just above on an older one).
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_validation_runs_suite ON validation_runs(suite_id)"
        )
        self._connection.commit()

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._connection.cursor()
        try:
            yield cur
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            cur.close()
