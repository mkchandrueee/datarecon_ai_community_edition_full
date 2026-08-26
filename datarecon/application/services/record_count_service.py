# datarecon/application/services/record_count_service.py
# Module 3: Record Count Validation.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from datarecon.application.services.data_extraction_service import DataExtractionService
from datarecon.application.services.run_recording import record_run
from datarecon.core.engine.duckdb_engine import (
    duckdb_connection,
    query_df,
    quote_identifier,
    registered_view,
)
from datarecon.domain.entities.project import DEFAULT_PROJECT_ID
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository
from datarecon.infrastructure.persistence.run_detail_store import RunDetailStore


@dataclass(frozen=True)
class RecordCountRequest:
    source_connection_id: str
    target_connection_id: str
    source_query: str | None = None
    target_query: str | None = None
    source_table: str | None = None
    target_table: str | None = None
    group_by: Sequence[str] = field(default_factory=tuple)
    tolerance_absolute: int = 0
    tolerance_percent: float = 0.0
    name: str = "Record Count Validation"


@dataclass
class RecordCountResult:
    source_count: int
    target_count: int
    difference: int
    variance_percent: float
    status: RunStatus
    group_breakdown: pd.DataFrame
    run: ValidationRun


class RecordCountService:
    def __init__(
        self,
        extraction: DataExtractionService,
        run_repository: IValidationRunRepository,
        detail_store: RunDetailStore,
    ):
        self._extraction = extraction
        self._runs = run_repository
        self._details = detail_store

    def execute(
        self,
        request: RecordCountRequest,
        project_id: str = DEFAULT_PROJECT_ID,
        suite_id: str | None = None,
    ) -> RecordCountResult:
        started = datetime.now(UTC)
        try:
            source_df = self._extraction.extract_dataframe(
                request.source_connection_id, query=request.source_query, table=request.source_table
            )
            target_df = self._extraction.extract_dataframe(
                request.target_connection_id, query=request.target_query, table=request.target_table
            )

            if request.group_by:
                breakdown = self._grouped_counts(source_df, target_df, list(request.group_by))
                source_count = int(breakdown["source_count"].sum())
                target_count = int(breakdown["target_count"].sum())
            else:
                breakdown = pd.DataFrame()
                source_count = len(source_df)
                target_count = len(target_df)

            difference = target_count - source_count
            variance_percent = self._variance_percent(source_count, difference)
            status = (
                RunStatus.PASS
                if abs(difference) <= request.tolerance_absolute
                or variance_percent <= request.tolerance_percent
                else RunStatus.FAIL
            )

            run = record_run(
                self._runs,
                ValidationModule.RECORD_COUNT,
                request.name,
                started,
                status,
                source_connection_id=request.source_connection_id,
                target_connection_id=request.target_connection_id,
                summary={
                    "source_count": source_count,
                    "target_count": target_count,
                    "difference": difference,
                    "variance_percent": variance_percent,
                },
                project_id=project_id,
                suite_id=suite_id,
            )
            if not breakdown.empty:
                self._details.save(run.run_id, {"Group Breakdown": breakdown})
            return RecordCountResult(
                source_count, target_count, difference, variance_percent, status, breakdown, run
            )
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.RECORD_COUNT,
                request.name,
                started,
                RunStatus.ERROR,
                source_connection_id=request.source_connection_id,
                target_connection_id=request.target_connection_id,
                error_message=str(exc),
                project_id=project_id,
                suite_id=suite_id,
            )
            raise

    @staticmethod
    def _variance_percent(source_count: int, difference: int) -> float:
        if source_count:
            return round(abs(difference) / source_count * 100.0, 4)
        return 0.0 if difference == 0 else 100.0

    @staticmethod
    def _grouped_counts(
        source_df: pd.DataFrame, target_df: pd.DataFrame, group_cols: list[str]
    ) -> pd.DataFrame:
        with (
            duckdb_connection() as con,
            registered_view(con, "src", source_df) as sv,
            registered_view(con, "tgt", target_df) as tv,
        ):
            cols_sql = ", ".join(quote_identifier(c) for c in group_cols)
            coalesced = ", ".join(
                f"COALESCE(s.{quote_identifier(c)}, t.{quote_identifier(c)}) AS {quote_identifier(c)}"
                for c in group_cols
            )
            sql = f"""
                WITH s AS (SELECT {cols_sql}, COUNT(*) AS source_count FROM {sv} GROUP BY {cols_sql}),
                     t AS (SELECT {cols_sql}, COUNT(*) AS target_count FROM {tv} GROUP BY {cols_sql})
                SELECT
                    {coalesced},
                    COALESCE(s.source_count, 0) AS source_count,
                    COALESCE(t.target_count, 0) AS target_count,
                    COALESCE(t.target_count, 0) - COALESCE(s.source_count, 0) AS difference
                FROM s FULL OUTER JOIN t USING ({cols_sql})
                ORDER BY {cols_sql}
            """
            breakdown = query_df(con, sql)
        breakdown["variance_percent"] = breakdown.apply(
            lambda r: RecordCountService._variance_percent(
                int(r["source_count"]), int(r["difference"])
            ),
            axis=1,
        )
        return breakdown
