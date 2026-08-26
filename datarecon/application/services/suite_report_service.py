# datarecon/application/services/suite_report_service.py
# Module-wise Test Suite reporting.
#
# The Test Suites page lists suites but not what they actually measured. This
# service joins each suite to its most recent run and groups the result by
# module, so a "Record Count Validation" section shows source count, target
# count and status side by side for every suite of that module — the numbers a
# reviewer wants, rather than a per-suite click-through.
#
# Summary keys differ per module (record count has source_count/target_count,
# full data has rows_matched/success_percentage), which is exactly why the
# report is grouped: suites within one module share a column set.
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.enums import ValidationModule
from datarecon.domain.interfaces.test_suite_repository import ITestSuiteRepository
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository

_NEVER_RUN = "never run"
_FIXED_COLUMNS = ["Test Suite", "Status", "Last Run"]


@dataclass(frozen=True)
class ModuleReport:
    module: ValidationModule
    table: pd.DataFrame

    @property
    def suite_count(self) -> int:
        return len(self.table)

    @property
    def passed(self) -> int:
        return int((self.table["Status"] == "PASS").sum()) if not self.table.empty else 0

    @property
    def failed(self) -> int:
        return int((self.table["Status"] == "FAIL").sum()) if not self.table.empty else 0


class SuiteReportService:
    def __init__(
        self,
        suite_repository: ITestSuiteRepository,
        run_repository: IValidationRunRepository,
    ):
        self._suites = suite_repository
        self._runs = run_repository

    def module_reports(self, project_id: str | None = None) -> list[ModuleReport]:
        """One report per module that has at least one saved suite, in the
        enum's declared order so the page layout is stable between renders."""
        suites = (
            self._suites.list_by_project(project_id) if project_id else self._suites.list_all()
        )
        by_module: dict[ValidationModule, list[TestSuite]] = {}
        for suite in suites:
            by_module.setdefault(suite.module, []).append(suite)

        return [
            ModuleReport(module, self._build_table(by_module[module]))
            for module in ValidationModule
            if module in by_module
        ]

    def _build_table(self, suites: list[TestSuite]) -> pd.DataFrame:
        rows = []
        for suite in sorted(suites, key=lambda s: s.name):
            row: dict[str, object] = {
                "Test Suite": suite.name,
                "Status": suite.last_run_status.value if suite.last_run_status else _NEVER_RUN,
                "Last Run": suite.last_run_at,
            }
            # A suite that has never run, or whose run predates this database,
            # still gets a row — its absence would read as "no such suite".
            run = self._runs.get_by_id(suite.last_run_id) if suite.last_run_id else None
            if run is not None:
                row.update({_humanise(k): v for k, v in run.summary.items()})
            rows.append(row)

        table = pd.DataFrame(rows)
        return table[_ordered_columns(table)] if not table.empty else table


def _humanise(key: str) -> str:
    return str(key).replace("_", " ").strip().title()


def _ordered_columns(table: pd.DataFrame) -> list[str]:
    """Identity columns first, then whatever metrics the module contributed."""
    fixed = [c for c in _FIXED_COLUMNS if c in table.columns]
    return fixed + [c for c in table.columns if c not in fixed]
