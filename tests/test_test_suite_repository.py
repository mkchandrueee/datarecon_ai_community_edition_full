"""Unit tests — SQLiteTestSuiteRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from datarecon.domain.entities.project import Project
from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.infrastructure.persistence.sqlite_project_repository import (
    SQLiteProjectRepository,
)
from datarecon.infrastructure.persistence.sqlite_test_suite_repository import (
    SQLiteTestSuiteRepository,
)


def _suite(project_id: str = "default", **overrides) -> TestSuite:
    defaults = {
        "project_id": project_id,
        "name": "Daily customers recon",
        "module": ValidationModule.RECORD_COUNT,
        "config": {"source_connection_id": "src", "target_connection_id": "tgt"},
    }
    defaults.update(overrides)
    return TestSuite(**defaults)


def test_add_and_get_roundtrip(test_suite_repository: SQLiteTestSuiteRepository) -> None:
    suite = _suite()
    test_suite_repository.add(suite)

    fetched = test_suite_repository.get_by_id(suite.suite_id)
    assert fetched is not None
    assert fetched.name == "Daily customers recon"
    assert fetched.module == ValidationModule.RECORD_COUNT
    assert fetched.config == {"source_connection_id": "src", "target_connection_id": "tgt"}
    assert fetched.schedule_enabled is False
    assert fetched.last_run_status is None


def test_get_by_id_returns_none_for_unknown(
    test_suite_repository: SQLiteTestSuiteRepository,
) -> None:
    assert test_suite_repository.get_by_id("does-not-exist") is None


def test_list_by_project(
    project_repository: SQLiteProjectRepository, test_suite_repository: SQLiteTestSuiteRepository
) -> None:
    other = project_repository.add(Project(name="Other Project"))
    test_suite_repository.add(_suite(name="a"))
    test_suite_repository.add(_suite(name="b", project_id=other.project_id))

    default_suites = test_suite_repository.list_by_project("default")
    assert [s.name for s in default_suites] == ["a"]


def test_delete(test_suite_repository: SQLiteTestSuiteRepository) -> None:
    suite = test_suite_repository.add(_suite())
    assert test_suite_repository.delete(suite.suite_id) is True
    assert test_suite_repository.get_by_id(suite.suite_id) is None


def test_record_run_result(test_suite_repository: SQLiteTestSuiteRepository) -> None:
    suite = test_suite_repository.add(_suite())
    when = datetime.now(UTC)
    test_suite_repository.record_run_result(suite.suite_id, "run-123", RunStatus.FAIL, when)

    fetched = test_suite_repository.get_by_id(suite.suite_id)
    assert fetched is not None
    assert fetched.last_run_id == "run-123"
    assert fetched.last_run_status == RunStatus.FAIL
    assert fetched.last_run_at is not None


def test_deleting_project_cascades_to_suites(
    project_repository: SQLiteProjectRepository, test_suite_repository: SQLiteTestSuiteRepository
) -> None:
    project = project_repository.add(Project(name="Cascade Target"))
    suite = test_suite_repository.add(_suite(project_id=project.project_id))

    project_repository.delete(project.project_id)

    assert test_suite_repository.get_by_id(suite.suite_id) is None
