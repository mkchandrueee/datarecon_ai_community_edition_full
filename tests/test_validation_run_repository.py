"""Unit tests — SQLiteValidationRunRepository (run-history persistence, ADR-0004)."""

from __future__ import annotations

from pathlib import Path

import pytest

from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase
from datarecon.infrastructure.persistence.sqlite_validation_run_repository import (
    SQLiteValidationRunRepository,
)


@pytest.fixture
def repo(tmp_path: Path) -> SQLiteValidationRunRepository:
    db = MetadataDatabase(tmp_path / "meta.db")
    return SQLiteValidationRunRepository(db)


def _run(**overrides) -> ValidationRun:
    defaults = {
        "module": ValidationModule.RECORD_COUNT,
        "name": "customers recon",
        "status": RunStatus.PASS,
        "summary": {"rows_source": 100, "rows_target": 100},
    }
    defaults.update(overrides)
    return ValidationRun(**defaults)


def test_add_and_get_roundtrip(repo: SQLiteValidationRunRepository) -> None:
    run = _run()
    repo.add(run)
    fetched = repo.get_by_id(run.run_id)
    assert fetched is not None
    assert fetched.module == ValidationModule.RECORD_COUNT
    assert fetched.status == RunStatus.PASS
    assert fetched.summary == {"rows_source": 100, "rows_target": 100}


def test_get_by_id_returns_none_for_unknown(repo: SQLiteValidationRunRepository) -> None:
    assert repo.get_by_id("does-not-exist") is None


def test_list_recent_orders_newest_first(repo: SQLiteValidationRunRepository) -> None:
    import time

    first = _run(name="first")
    repo.add(first)
    time.sleep(0.01)
    second = _run(name="second")
    repo.add(second)

    recent = repo.list_recent()
    assert [r.name for r in recent[:2]] == ["second", "first"]


def test_list_recent_respects_limit(repo: SQLiteValidationRunRepository) -> None:
    for i in range(5):
        repo.add(_run(name=f"run-{i}"))
    assert len(repo.list_recent(limit=3)) == 3


def test_list_by_module_filters(repo: SQLiteValidationRunRepository) -> None:
    repo.add(_run(module=ValidationModule.RECORD_COUNT, name="rc"))
    repo.add(_run(module=ValidationModule.SCHEMA, name="schema"))

    schema_runs = repo.list_by_module(ValidationModule.SCHEMA)
    assert len(schema_runs) == 1
    assert schema_runs[0].name == "schema"


def test_error_run_persists_error_message(repo: SQLiteValidationRunRepository) -> None:
    run = _run(status=RunStatus.ERROR, error_message="connection refused")
    repo.add(run)
    fetched = repo.get_by_id(run.run_id)
    assert fetched is not None
    assert fetched.status == RunStatus.ERROR
    assert fetched.error_message == "connection refused"


def test_run_defaults_to_default_project(repo: SQLiteValidationRunRepository) -> None:
    run = _run()
    repo.add(run)
    fetched = repo.get_by_id(run.run_id)
    assert fetched is not None
    assert fetched.project_id == "default"


def test_list_by_project_filters(repo: SQLiteValidationRunRepository) -> None:
    repo.add(_run(name="a", project_id="proj-a"))
    repo.add(_run(name="b", project_id="proj-b"))
    repo.add(_run(name="c", project_id="proj-a"))

    proj_a_runs = repo.list_by_project("proj-a")
    assert sorted(r.name for r in proj_a_runs) == ["a", "c"]


def test_list_by_project_respects_limit(repo: SQLiteValidationRunRepository) -> None:
    for i in range(5):
        repo.add(_run(name=f"run-{i}", project_id="proj-a"))
    assert len(repo.list_by_project("proj-a", limit=2)) == 2


def test_list_filtered_no_filters_returns_all(repo: SQLiteValidationRunRepository) -> None:
    repo.add(_run(name="a", module=ValidationModule.SCHEMA, project_id="proj-a"))
    repo.add(_run(name="b", module=ValidationModule.RECORD_COUNT, project_id="proj-b"))

    assert len(repo.list_filtered()) == 2


def test_list_filtered_by_project_only(repo: SQLiteValidationRunRepository) -> None:
    repo.add(_run(name="a", module=ValidationModule.SCHEMA, project_id="proj-a"))
    repo.add(_run(name="b", module=ValidationModule.RECORD_COUNT, project_id="proj-a"))
    repo.add(_run(name="c", module=ValidationModule.SCHEMA, project_id="proj-b"))

    results = repo.list_filtered(project_id="proj-a")
    assert sorted(r.name for r in results) == ["a", "b"]


def test_list_filtered_by_module_only(repo: SQLiteValidationRunRepository) -> None:
    repo.add(_run(name="a", module=ValidationModule.SCHEMA, project_id="proj-a"))
    repo.add(_run(name="b", module=ValidationModule.RECORD_COUNT, project_id="proj-b"))

    results = repo.list_filtered(module=ValidationModule.SCHEMA)
    assert [r.name for r in results] == ["a"]


def test_list_filtered_by_project_and_module(repo: SQLiteValidationRunRepository) -> None:
    repo.add(_run(name="a", module=ValidationModule.SCHEMA, project_id="proj-a"))
    repo.add(_run(name="b", module=ValidationModule.RECORD_COUNT, project_id="proj-a"))
    repo.add(_run(name="c", module=ValidationModule.SCHEMA, project_id="proj-b"))

    results = repo.list_filtered(project_id="proj-a", module=ValidationModule.SCHEMA)
    assert [r.name for r in results] == ["a"]


def test_list_filtered_respects_limit(repo: SQLiteValidationRunRepository) -> None:
    for i in range(5):
        repo.add(_run(name=f"run-{i}", project_id="proj-a"))
    assert len(repo.list_filtered(project_id="proj-a", limit=2)) == 2


def test_run_defaults_to_no_suite(repo: SQLiteValidationRunRepository) -> None:
    run = _run()
    repo.add(run)
    fetched = repo.get_by_id(run.run_id)
    assert fetched is not None
    assert fetched.suite_id is None


def test_list_filtered_by_suite_only(repo: SQLiteValidationRunRepository) -> None:
    repo.add(_run(name="a", suite_id="suite-1"))
    repo.add(_run(name="b", suite_id="suite-2"))
    repo.add(_run(name="c", suite_id="suite-1"))

    results = repo.list_filtered(suite_id="suite-1")
    assert sorted(r.name for r in results) == ["a", "c"]


def test_list_filtered_by_project_module_and_suite(repo: SQLiteValidationRunRepository) -> None:
    repo.add(
        _run(
            name="a",
            module=ValidationModule.SCHEMA,
            project_id="proj-a",
            suite_id="suite-1",
        )
    )
    repo.add(
        _run(
            name="b",
            module=ValidationModule.SCHEMA,
            project_id="proj-a",
            suite_id="suite-2",
        )
    )
    repo.add(
        _run(
            name="c",
            module=ValidationModule.RECORD_COUNT,
            project_id="proj-a",
            suite_id="suite-1",
        )
    )

    results = repo.list_filtered(
        project_id="proj-a", module=ValidationModule.SCHEMA, suite_id="suite-1"
    )
    assert [r.name for r in results] == ["a"]
