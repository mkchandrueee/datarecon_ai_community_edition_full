# datarecon/application/services/nullability_validation_service.py
# Module 5: Nullability / Completeness Validation.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from datarecon.application.services.data_extraction_service import DataExtractionService
from datarecon.application.services.run_recording import record_run
from datarecon.core.column_matching import resolve_all
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

_DEFAULT_SENTINELS: tuple[str, ...] = ("N/A", "NA", "NULL", "None", "-", "-999", "1900-01-01")


class NullabilityValidationError(ValueError):
    """Raised for malformed nullability-validation requests."""


@dataclass(frozen=True)
class NullabilityValidationRequest:
    connection_id: str
    query: str | None = None
    table: str | None = None
    columns: Sequence[str] = field(default_factory=tuple)
    sentinel_values: Sequence[str] = _DEFAULT_SENTINELS
    completeness_threshold_percent: float = 100.0
    name: str = "Nullability Validation"


@dataclass
class NullabilityValidationResult:
    total_rows: int
    completeness_score: float
    status: RunStatus
    column_stats: pd.DataFrame
    run: ValidationRun


class NullabilityValidationService:
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
        request: NullabilityValidationRequest,
        project_id: str = DEFAULT_PROJECT_ID,
        suite_id: str | None = None,
    ) -> NullabilityValidationResult:
        started = datetime.now(UTC)
        try:
            df = self._extraction.extract_dataframe(
                request.connection_id, query=request.query, table=request.table
            )
            requested = list(request.columns)
            if requested:
                # Resolve case-insensitively (ADR-0009) — a column typed
                # as customer_id still finds CUSTOMER_ID in the data.
                columns, missing = resolve_all(requested, df.columns)
                if missing:
                    raise NullabilityValidationError(f"Column(s) not found: {missing}")
            else:
                columns = list(df.columns)

            total_rows, column_stats = self._analyze(df, columns, list(request.sentinel_values))
            completeness_score = (
                round(column_stats["completeness_percent"].mean(), 4)
                if len(column_stats)
                else 100.0
            )
            status = (
                RunStatus.PASS
                if completeness_score >= request.completeness_threshold_percent
                else RunStatus.FAIL
            )

            run = record_run(
                self._runs,
                ValidationModule.NULLABILITY,
                request.name,
                started,
                status,
                source_connection_id=request.connection_id,
                summary={"total_rows": total_rows, "completeness_score": completeness_score},
                project_id=project_id,
                suite_id=suite_id,
            )
            self._details.save(run.run_id, {"Column Statistics": column_stats})
            return NullabilityValidationResult(
                total_rows, completeness_score, status, column_stats, run
            )
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.NULLABILITY,
                request.name,
                started,
                RunStatus.ERROR,
                source_connection_id=request.connection_id,
                error_message=str(exc),
                project_id=project_id,
                suite_id=suite_id,
            )
            raise

    @staticmethod
    def _analyze(
        df: pd.DataFrame, columns: list[str], sentinel_values: list[str]
    ) -> tuple[int, pd.DataFrame]:
        with duckdb_connection() as con, registered_view(con, "src", df) as view:
            total_rows = int(query_df(con, f"SELECT COUNT(*) AS n FROM {view}")["n"].iloc[0])
            if total_rows == 0 or not columns:
                return total_rows, pd.DataFrame(
                    columns=[
                        "column",
                        "null_count",
                        "blank_count",
                        "sentinel_count",
                        "missing_count",
                        "completeness_percent",
                    ]
                )

            sentinel_list_sql = ", ".join(
                f"'{v.replace(chr(39), chr(39) * 2)}'" for v in sentinel_values
            )
            blocks = []
            for col in columns:
                q = quote_identifier(col)
                blocks.append(f"""
                    SELECT
                        '{col.replace(chr(39), chr(39) * 2)}' AS column,
                        COUNT(*) FILTER (WHERE {q} IS NULL) AS null_count,
                        COUNT(*) FILTER (
                            WHERE {q} IS NOT NULL AND TRIM(CAST({q} AS VARCHAR)) = ''
                        ) AS blank_count,
                        COUNT(*) FILTER (
                            WHERE {q} IS NOT NULL AND CAST({q} AS VARCHAR) IN ({sentinel_list_sql})
                        ) AS sentinel_count
                    FROM {view}
                """)
            sql = "\nUNION ALL\n".join(blocks)
            stats = query_df(con, sql)

        stats["missing_count"] = (
            stats["null_count"] + stats["blank_count"] + stats["sentinel_count"]
        )
        stats["completeness_percent"] = round(
            (total_rows - stats["missing_count"]) / total_rows * 100.0, 4
        )
        return total_rows, stats
