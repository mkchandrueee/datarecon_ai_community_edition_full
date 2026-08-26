"""Unit tests — SuiteReportService (module-wise Test Suite reporting)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from datarecon.application.services.suite_report_service import SuiteReportService
from datarecon.domain.entities.project import Project
from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule


@pytest.fixture
def service(test_suite_repository, run_repository) -> SuiteReportService:
    return SuiteReportService(test_suite_repository, run_repository)


def _save_suite(repo, name, module, project_id="default") -> TestSuite:
    return repo.add(
        TestSuite(project_id=project_id, name=name, module=module, config={})
    )


def _record_run(repo, module, summary, status=RunStatus.PASS) -> ValidationRun:
    return repo.add(
        ValidationRun(module=module, name="run", status=status, summary=summary)
    )


def test_no_suites_gives_no_reports(service: SuiteReportService) -> None:
    assert service.module_reports() == []


def test_one_report_per_module(service, test_suite_repository) -> None:
    _save_suite(test_suite_repository, "RC_A", ValidationModule.RECORD_COUNT)
    _save_suite(test_suite_repository, "RC_B", ValidationModule.RECORD_COUNT)
    _save_suite(test_suite_repository, "SC_A", ValidationModule.SCHEMA)

    reports = service.module_reports()

    assert [r.module for r in reports] == [
        ValidationModule.SCHEMA,
        ValidationModule.RECORD_COUNT,
    ]  # enum declaration order, not insertion order
    assert {r.module: r.suite_count for r in reports} == {
        ValidationModule.SCHEMA: 1,
        ValidationModule.RECORD_COUNT: 2,
    }


def test_summary_metrics_become_columns(service, test_suite_repository, run_repository) -> None:
    suite = _save_suite(test_suite_repository, "RC_ORDERS", ValidationModule.RECORD_COUNT)
    run = _record_run(
        run_repository,
        ValidationModule.RECORD_COUNT,
        {"source_count": 10, "target_count": 10, "difference": 0},
    )
    test_suite_repository.record_run_result(
        suite.suite_id, run.run_id, RunStatus.PASS, datetime.now(UTC)
    )

    table = service.module_reports()[0].table

    assert table["Source Count"].iloc[0] == 10
    assert table["Target Count"].iloc[0] == 10
    assert table["Difference"].iloc[0] == 0


def test_identity_columns_come_first(service, test_suite_repository, run_repository) -> None:
    suite = _save_suite(test_suite_repository, "RC_ORDERS", ValidationModule.RECORD_COUNT)
    run = _record_run(run_repository, ValidationModule.RECORD_COUNT, {"source_count": 1})
    test_suite_repository.record_run_result(
        suite.suite_id, run.run_id, RunStatus.PASS, datetime.now(UTC)
    )

    table = service.module_reports()[0].table

    assert list(table.columns)[:3] == ["Test Suite", "Status", "Last Run"]


def test_never_run_suite_still_appears(service, test_suite_repository) -> None:
    _save_suite(test_suite_repository, "RC_NEW", ValidationModule.RECORD_COUNT)

    table = service.module_reports()[0].table

    assert table["Test Suite"].iloc[0] == "RC_NEW"
    assert table["Status"].iloc[0] == "never run"


def test_pass_fail_counts(service, test_suite_repository, run_repository) -> None:
    passing = _save_suite(test_suite_repository, "RC_A", ValidationModule.RECORD_COUNT)
    failing = _save_suite(test_suite_repository, "RC_B", ValidationModule.RECORD_COUNT)
    _save_suite(test_suite_repository, "RC_C", ValidationModule.RECORD_COUNT)

    when = datetime.now(UTC)
    ok = _record_run(run_repository, ValidationModule.RECORD_COUNT, {"source_count": 1})
    bad = _record_run(
        run_repository, ValidationModule.RECORD_COUNT, {"source_count": 2}, RunStatus.FAIL
    )
    test_suite_repository.record_run_result(passing.suite_id, ok.run_id, RunStatus.PASS, when)
    test_suite_repository.record_run_result(failing.suite_id, bad.run_id, RunStatus.FAIL, when)

    report = service.module_reports()[0]

    assert report.suite_count == 3
    assert report.passed == 1
    assert report.failed == 1


def test_filters_by_project(service, test_suite_repository, project_repository) -> None:
    other = project_repository.add(Project(name="Other"))
    _save_suite(test_suite_repository, "RC_DEFAULT", ValidationModule.RECORD_COUNT)
    _save_suite(
        test_suite_repository, "RC_OTHER", ValidationModule.RECORD_COUNT, other.project_id
    )

    reports = service.module_reports(project_id=other.project_id)

    assert len(reports) == 1
    assert reports[0].table["Test Suite"].tolist() == ["RC_OTHER"]


def test_suites_are_sorted_by_name(service, test_suite_repository) -> None:
    _save_suite(test_suite_repository, "RC_Z", ValidationModule.RECORD_COUNT)
    _save_suite(test_suite_repository, "RC_A", ValidationModule.RECORD_COUNT)

    table = service.module_reports()[0].table

    assert table["Test Suite"].tolist() == ["RC_A", "RC_Z"]
