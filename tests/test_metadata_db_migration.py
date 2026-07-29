"""Unit tests — MetadataDatabase backward-compatible column migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase


def _create_pre_migration_schema(db_path: Path) -> None:
    """Simulate a database created before `project_id` existed on
    `validation_runs`, to prove opening it with the current code migrates
    it in place instead of crashing on missing-column errors."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE validation_runs (
            run_id                  TEXT PRIMARY KEY,
            module                  TEXT NOT NULL,
            name                    TEXT NOT NULL,
            status                  TEXT NOT NULL,
            summary_json            TEXT NOT NULL,
            source_connection_id    TEXT,
            target_connection_id    TEXT,
            error_message           TEXT,
            runtime_seconds         REAL NOT NULL DEFAULT 0,
            started_at              TEXT NOT NULL,
            finished_at             TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO validation_runs "
        "(run_id, module, name, status, summary_json, runtime_seconds, started_at, finished_at) "
        "VALUES ('r1', 'Schema Validation', 'legacy run', 'PASS', '{}', 1.0, "
        "'2024-01-01T00:00:00+00:00', '2024-01-01T00:00:01+00:00')"
    )
    conn.commit()
    conn.close()


def _create_pre_suite_id_schema(db_path: Path) -> None:
    """Simulate a database that already has `project_id` (an earlier
    migration) but predates `suite_id`."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE validation_runs (
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
            started_at              TEXT NOT NULL,
            finished_at             TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO validation_runs "
        "(run_id, module, name, status, summary_json, runtime_seconds, project_id, "
        "started_at, finished_at) "
        "VALUES ('r1', 'Schema Validation', 'legacy run', 'PASS', '{}', 1.0, 'default', "
        "'2024-01-01T00:00:00+00:00', '2024-01-01T00:00:01+00:00')"
    )
    conn.commit()
    conn.close()


def test_opening_pre_migration_db_adds_project_id_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _create_pre_migration_schema(db_path)

    db = MetadataDatabase(db_path)

    with db.cursor() as cur:
        cur.execute("SELECT project_id FROM validation_runs WHERE run_id='r1'")
        row = cur.fetchone()
    assert row["project_id"] == "default"


def test_opening_pre_migration_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _create_pre_migration_schema(db_path)

    MetadataDatabase(db_path)
    second_open = MetadataDatabase(db_path)  # must not raise "duplicate column"

    with second_open.cursor() as cur:
        cur.execute("SELECT project_id FROM validation_runs WHERE run_id='r1'")
        row = cur.fetchone()
    assert row["project_id"] == "default"


def test_opening_pre_migration_db_adds_suite_id_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _create_pre_migration_schema(db_path)

    db = MetadataDatabase(db_path)

    with db.cursor() as cur:
        cur.execute("SELECT suite_id FROM validation_runs WHERE run_id='r1'")
        row = cur.fetchone()
    assert row["suite_id"] is None


def test_opening_db_with_project_id_but_not_suite_id_adds_suite_id(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _create_pre_suite_id_schema(db_path)

    db = MetadataDatabase(db_path)

    with db.cursor() as cur:
        cur.execute("SELECT project_id, suite_id FROM validation_runs WHERE run_id='r1'")
        row = cur.fetchone()
    assert row["project_id"] == "default"
    assert row["suite_id"] is None
