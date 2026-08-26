# datarecon/application/services/dashboard_service.py
# Module 19: Reconciliation Dashboard (Community Edition scope — see
# ADR-0002: no role-scoped/embeddable dashboards, no "running"/incident/
# freshness widgets since those depend on Enterprise-only scheduling
# (Module 17) and observability (Module 11)).
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository

_DEFAULT_LIMIT = 500


@dataclass(frozen=True)
class DashboardWidgets:
    total_runs: int
    passed: int
    failed: int
    errored: int
    pass_rate_percent: float


@dataclass(frozen=True)
class ProjectReport:
    """A project's dashboard state, shaped for Module 18's exporters."""

    project_name: str
    summary: dict[str, object]
    runs_by_module: pd.DataFrame
    pass_rate_trend: pd.DataFrame
    run_history: pd.DataFrame

    def sections(self) -> list[tuple[str, pd.DataFrame]]:
        """Named tables in reading order; empty ones are dropped so an export
        never carries a blank sheet."""
        candidates = [
            ("Runs by Module", self.runs_by_module),
            ("Pass Rate Trend", self.pass_rate_trend),
            ("Run History", self.run_history),
        ]
        return [(title, table) for title, table in candidates if not table.empty]


class DashboardService:
    def __init__(self, run_repository: IValidationRunRepository):
        self._runs = run_repository

    def _fetch(self, limit: int, project_id: str | None) -> list[ValidationRun]:
        # Archived runs are deliberately excluded: a superseded failure the
        # user archived shouldn't keep dragging the pass rate down.
        return self._runs.list_filtered(project_id=project_id, limit=limit)

    def widgets(self, limit: int = _DEFAULT_LIMIT, project_id: str | None = None) -> DashboardWidgets:
        return self._summarize(self._fetch(limit, project_id))

    @staticmethod
    def _summarize(runs: list[ValidationRun]) -> DashboardWidgets:
        total = len(runs)
        passed = sum(1 for r in runs if r.status == RunStatus.PASS)
        failed = sum(1 for r in runs if r.status == RunStatus.FAIL)
        errored = sum(1 for r in runs if r.status == RunStatus.ERROR)
        pass_rate = round(passed / total * 100.0, 2) if total else 0.0
        return DashboardWidgets(total, passed, failed, errored, pass_rate)

    def pass_rate_trend(
        self, limit: int = _DEFAULT_LIMIT, project_id: str | None = None
    ) -> pd.DataFrame:
        runs = self._fetch(limit, project_id)
        columns = ["date", "total", "passed", "pass_rate_percent"]
        if not runs:
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame([{"date": r.started_at.date(), "status": r.status.value} for r in runs])
        grouped = (
            df.groupby("date")["status"]
            .agg(total="count", passed=lambda s: (s == RunStatus.PASS.value).sum())
            .reset_index()
        )
        grouped["pass_rate_percent"] = round(grouped["passed"] / grouped["total"] * 100.0, 2)
        return grouped.sort_values("date").reset_index(drop=True)[columns]

    def runs_by_module(
        self, limit: int = _DEFAULT_LIMIT, project_id: str | None = None
    ) -> pd.DataFrame:
        runs = self._fetch(limit, project_id)
        columns = ["module", "total", "passed", "failed", "errored"]
        if not runs:
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame([{"module": r.module.value, "status": r.status.value} for r in runs])
        grouped = df.groupby("module")["status"].value_counts().unstack(fill_value=0)
        for status in (RunStatus.PASS, RunStatus.FAIL, RunStatus.ERROR):
            if status.value not in grouped.columns:
                grouped[status.value] = 0
        grouped = grouped.rename(
            columns={"PASS": "passed", "FAIL": "failed", "ERROR": "errored"}
        ).reset_index()
        grouped["total"] = grouped["passed"] + grouped["failed"] + grouped["errored"]
        return grouped[columns].sort_values("total", ascending=False).reset_index(drop=True)

    def run_history(
        self, limit: int = _DEFAULT_LIMIT, project_id: str | None = None
    ) -> pd.DataFrame:
        """Flat run list backing the project report's detail section."""
        runs = self._fetch(limit, project_id)
        columns = ["started_at", "module", "name", "status", "runtime_seconds", "error_message"]
        if not runs:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(
            [
                {
                    "started_at": r.started_at,
                    "module": r.module.value,
                    "name": r.name,
                    "status": r.status.value,
                    "runtime_seconds": r.runtime_seconds,
                    "error_message": r.error_message or "",
                }
                for r in runs
            ]
        )
        return df.sort_values("started_at", ascending=False).reset_index(drop=True)[columns]

    def project_report(
        self, project_name: str, limit: int = _DEFAULT_LIMIT, project_id: str | None = None
    ) -> ProjectReport:
        """Everything the dashboard shows, packaged for export in one call, so
        the PDF/Excel/CSV a reviewer receives matches the screen they saw."""
        widgets = self.widgets(limit, project_id)
        return ProjectReport(
            project_name=project_name,
            summary={
                "project": project_name,
                "total_runs": widgets.total_runs,
                "passed": widgets.passed,
                "failed": widgets.failed,
                "errored": widgets.errored,
                "pass_rate_percent": widgets.pass_rate_percent,
            },
            runs_by_module=self.runs_by_module(limit, project_id),
            pass_rate_trend=self.pass_rate_trend(limit, project_id),
            run_history=self.run_history(limit, project_id),
        )

    def runtime_trend(
        self, limit: int = _DEFAULT_LIMIT, project_id: str | None = None
    ) -> pd.DataFrame:
        runs = self._fetch(limit, project_id)
        columns = ["started_at", "module", "runtime_seconds"]
        if not runs:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(
            [
                {
                    "started_at": r.started_at,
                    "module": r.module.value,
                    "runtime_seconds": r.runtime_seconds,
                }
                for r in runs
            ]
        )
        return df.sort_values("started_at").reset_index(drop=True)[columns]
