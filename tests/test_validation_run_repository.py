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


# ---------- manual archiving ----------


def _added_run(repo, **kwargs) -> ValidationRun:
    defaults = {
        "module": ValidationModule.RECORD_COUNT,
        "name": "RC_ORDERS",
        "status": RunStatus.FAIL,
    }
    return repo.add(ValidationRun(**{**defaults, **kwargs}))


def test_runs_are_not_archived_by_default(repo) -> None:
    run = _added_run(repo)
    assert repo.get_by_id(run.run_id).archived is False


def test_set_archived_hides_run_from_default_listing(repo) -> None:
    run = _added_run(repo)
    assert repo.set_archived(run.run_id, True) is True

    visible = repo.list_filtered()
    assert run.run_id not in [r.run_id for r in visible]

    with_archived = repo.list_filtered(include_archived=True)
    assert run.run_id in [r.run_id for r in with_archived]


def test_archived_flag_round_trips(repo) -> None:
    run = _added_run(repo)
    repo.set_archived(run.run_id, True)
    assert repo.get_by_id(run.run_id).archived is True


def test_archiving_is_reversible(repo) -> None:
    run = _added_run(repo)
    repo.set_archived(run.run_id, True)
    repo.set_archived(run.run_id, False)

    assert repo.get_by_id(run.run_id).archived is False
    assert run.run_id in [r.run_id for r in repo.list_filtered()]


def test_set_archived_on_unknown_run_returns_false(repo) -> None:
    assert repo.set_archived("does-not-exist", True) is False


def test_archive_respects_other_filters(repo) -> None:
    kept = _added_run(repo, project_id="p1")
    archived = _added_run(repo, project_id="p1")
    _added_run(repo, project_id="p2")
    repo.set_archived(archived.run_id, True)

    visible = repo.list_filtered(project_id="p1")
    assert [r.run_id for r in visible] == [kept.run_id]


# ---------- permanent deletion (ADR-0016) ----------


def test_delete_removes_a_run(repo) -> None:
    run = _added_run(repo, name="GONE")

    assert repo.delete(run.run_id) is True
    assert repo.get_by_id(run.run_id) is None


def test_delete_reports_false_for_an_unknown_run(repo) -> None:
    assert repo.delete("no-such-run") is False


def test_delete_leaves_the_other_runs(repo) -> None:
    keep = _added_run(repo, name="KEEP")
    drop = _added_run(repo, name="DROP")

    repo.delete(drop.run_id)

    assert [r.run_id for r in repo.list_recent()] == [keep.run_id]
