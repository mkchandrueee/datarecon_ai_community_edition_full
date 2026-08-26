"""Unit tests — DashboardService (Module 19)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from datarecon.application.services.dashboard_service import DashboardService
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule


def _seed(run_repository, module, status, started_at, runtime=1.0, project_id="default") -> None:
    run_repository.add(
        ValidationRun(
            module=module,
            name=f"{module.value} run",
            status=status,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=runtime),
            runtime_seconds=runtime,
            project_id=project_id,
        )
    )


@pytest.fixture
def service(run_repository) -> DashboardService:
    return DashboardService(run_repository)


def test_widgets_empty_history(service: DashboardService) -> None:
    widgets = service.widgets()
    assert widgets.total_runs == 0
    assert widgets.pass_rate_percent == 0.0


def test_widgets_counts_by_status(service: DashboardService, run_repository) -> None:
    now = datetime.now(UTC)
    _seed(run_repository, ValidationModule.RECORD_COUNT, RunStatus.PASS, now)
    _seed(run_repository, ValidationModule.RECORD_COUNT, RunStatus.PASS, now)
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.FAIL, now)
    _seed(run_repository, ValidationModule.DUPLICATE, RunStatus.ERROR, now)

    widgets = service.widgets()
    assert widgets.total_runs == 4
    assert widgets.passed == 2
    assert widgets.failed == 1
    assert widgets.errored == 1
    assert widgets.pass_rate_percent == 50.0


def test_pass_rate_trend_groups_by_day(service: DashboardService, run_repository) -> None:
    day1 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    day2 = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    _seed(run_repository, ValidationModule.RECORD_COUNT, RunStatus.PASS, day1)
    _seed(run_repository, ValidationModule.RECORD_COUNT, RunStatus.FAIL, day1)
    _seed(run_repository, ValidationModule.RECORD_COUNT, RunStatus.PASS, day2)

    trend = service.pass_rate_trend()
    assert len(trend) == 2
    first_day = trend[trend["date"] == day1.date()].iloc[0]
    assert first_day["total"] == 2
    assert first_day["passed"] == 1
    assert first_day["pass_rate_percent"] == 50.0


def test_pass_rate_trend_empty(service: DashboardService) -> None:
    trend = service.pass_rate_trend()
    assert list(trend.columns) == ["date", "total", "passed", "pass_rate_percent"]
    assert len(trend) == 0


def test_runs_by_module_breakdown(service: DashboardService, run_repository) -> None:
    now = datetime.now(UTC)
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.PASS, now)
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.FAIL, now)
    _seed(run_repository, ValidationModule.DUPLICATE, RunStatus.PASS, now)

    breakdown = service.runs_by_module().set_index("module")
    assert breakdown.loc["Schema Validation", "total"] == 2
    assert breakdown.loc["Schema Validation", "passed"] == 1
    assert breakdown.loc["Schema Validation", "failed"] == 1
    assert breakdown.loc["Duplicate Validation", "passed"] == 1


def test_runtime_trend_sorted_ascending(service: DashboardService, run_repository) -> None:
    now = datetime.now(UTC)
    _seed(
        run_repository,
        ValidationModule.SCHEMA,
        RunStatus.PASS,
        now + timedelta(seconds=10),
        runtime=2.0,
    )
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.PASS, now, runtime=1.0)

    trend = service.runtime_trend()
    assert list(trend["runtime_seconds"]) == [1.0, 2.0]


def test_widgets_respects_limit(service: DashboardService, run_repository) -> None:
    now = datetime.now(UTC)
    for _ in range(10):
        _seed(run_repository, ValidationModule.SCHEMA, RunStatus.PASS, now)

    widgets = service.widgets(limit=3)
    assert widgets.total_runs == 3


def test_widgets_filters_by_project(service: DashboardService, run_repository) -> None:
    now = datetime.now(UTC)
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.PASS, now, project_id="default")
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.FAIL, now, project_id="proj-a")
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.FAIL, now, project_id="proj-a")

    assert service.widgets().total_runs == 3
    assert service.widgets(project_id="default").total_runs == 1
    assert service.widgets(project_id="proj-a").total_runs == 2
    assert service.widgets(project_id="proj-a").failed == 2


def test_runs_by_module_filters_by_project(service: DashboardService, run_repository) -> None:
    now = datetime.now(UTC)
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.PASS, now, project_id="proj-a")
    _seed(run_repository, ValidationModule.DUPLICATE, RunStatus.PASS, now, project_id="proj-b")

    breakdown = service.runs_by_module(project_id="proj-a")
    assert list(breakdown["module"]) == ["Schema Validation"]


def test_runtime_trend_filters_by_project(service: DashboardService, run_repository) -> None:
    now = datetime.now(UTC)
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.PASS, now, project_id="proj-a")
    _seed(run_repository, ValidationModule.SCHEMA, RunStatus.PASS, now, project_id="proj-b")

    trend = service.runtime_trend(project_id="proj-a")
    assert len(trend) == 1


def test_pass_rate_trend_filters_by_project(service: DashboardService, run_repository) -> None:
    day1 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    _seed(run_repository, ValidationModule.RECORD_COUNT, RunStatus.PASS, day1, project_id="proj-a")
    _seed(run_repository, ValidationModule.RECORD_COUNT, RunStatus.FAIL, day1, project_id="proj-b")

    trend = service.pass_rate_trend(project_id="proj-a")
    assert len(trend) == 1
    assert trend.iloc[0]["pass_rate_percent"] == 100.0


# ---------- project report export (overall results, PDF/Excel/CSV) ----------

def _add(run_repository, status, module=ValidationModule.RECORD_COUNT) -> ValidationRun:
    """Seed one run and hand it back, for tests that need its id or name."""
    run = ValidationRun(
        module=module,
        name=f"{module.value} {status.value}",
        status=status,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    return run_repository.add(run)




def test_project_report_summary_matches_widgets(service, run_repository) -> None:
    _add(run_repository, RunStatus.PASS)
    _add(run_repository, RunStatus.PASS)
    _add(run_repository, RunStatus.FAIL)

    report = service.project_report("All Projects")

    assert report.project_name == "All Projects"
    assert report.summary["total_runs"] == 3
    assert report.summary["passed"] == 2
    assert report.summary["failed"] == 1
    assert report.summary["pass_rate_percent"] == pytest.approx(66.67, abs=0.01)


def test_project_report_sections_drop_empty_tables(service) -> None:
    report = service.project_report("Empty")
    assert report.sections() == []


def test_project_report_sections_are_named_and_ordered(service, run_repository) -> None:
    _add(run_repository, RunStatus.PASS)

    titles = [title for title, _ in service.project_report("P").sections()]

    assert titles == ["Runs by Module", "Pass Rate Trend", "Run History"]


def test_run_history_lists_each_run(service, run_repository) -> None:
    _add(run_repository, RunStatus.PASS)
    _add(run_repository, RunStatus.FAIL)

    history = service.run_history()

    assert len(history) == 2
    assert set(history["status"]) == {"PASS", "FAIL"}


def test_run_history_is_empty_frame_with_columns_when_no_runs(service) -> None:
    history = service.run_history()
    assert history.empty
    assert "started_at" in history.columns


def test_archived_runs_are_excluded_from_the_dashboard(service, run_repository) -> None:
    kept = _add(run_repository, RunStatus.PASS)
    archived = _add(run_repository, RunStatus.FAIL)
    run_repository.set_archived(archived.run_id, True)

    widgets = service.widgets()

    assert widgets.total_runs == 1
    assert widgets.failed == 0
    assert service.run_history()["name"].tolist() == [kept.name]
