# datarecon/application/services/profiling_service.py
# Module 10: Data Profiling.
#
# Profiling is exploratory, not a pass/fail gate — the run always records
# PASS unless extraction/analysis itself raises. Semantic type inference is
# a lightweight regex heuristic over a sample, not an ML/NER classifier
# (that belongs to the Enterprise PII Detection module, out of scope here
# per ADR-0002).
from __future__ import annotations

import re
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

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[\d\-().\s]{7,20}$")
_SEMANTIC_SAMPLE_SIZE = 500
_SEMANTIC_MATCH_THRESHOLD = 0.8


class ProfilingError(ValueError):
    """Raised for malformed profiling requests."""


@dataclass(frozen=True)
class ProfilingRequest:
    connection_id: str
    query: str | None = None
    table: str | None = None
    columns: Sequence[str] = field(default_factory=tuple)
    top_n: int = 5
    name: str = "Data Profiling"


@dataclass
class ProfilingResult:
    total_rows: int
    column_profiles: pd.DataFrame
    top_values: dict[str, pd.DataFrame]
    run: ValidationRun


class ProfilingService:
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
        self, request: ProfilingRequest, project_id: str = DEFAULT_PROJECT_ID
    ) -> ProfilingResult:
        started = datetime.now(UTC)
        try:
            df = self._extraction.extract_dataframe(
                request.connection_id, query=request.query, table=request.table
            )
            requested = list(request.columns)
            if requested:
                # Resolve case-insensitively (ADR-0009).
                columns, missing = resolve_all(requested, df.columns)
                if missing:
                    raise ProfilingError(f"Column(s) not found: {missing}")
            else:
                columns = list(df.columns)

            total_rows = len(df)
            profiles = pd.DataFrame([self._profile_column(df, col, total_rows) for col in columns])
            top_values = {
                col: df[col]
                .value_counts(dropna=True)
                .head(request.top_n)
                .rename_axis("value")
                .reset_index(name="frequency")
                for col in columns
            }

            run = record_run(
                self._runs,
                ValidationModule.PROFILING,
                request.name,
                started,
                RunStatus.PASS,
                source_connection_id=request.connection_id,
                summary={"total_rows": total_rows, "columns_profiled": len(columns)},
                project_id=project_id,
            )
            details = {"Column Profiles": profiles}
            details.update(
                {f"Top Values - {col}": df for col, df in top_values.items() if not df.empty}
            )
            self._details.save(run.run_id, details)
            return ProfilingResult(total_rows, profiles, top_values, run)
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.PROFILING,
                request.name,
                started,
                RunStatus.ERROR,
                source_connection_id=request.connection_id,
                error_message=str(exc),
                project_id=project_id,
            )
            raise

    @classmethod
    def _profile_column(cls, df: pd.DataFrame, col: str, total_rows: int) -> dict:
        series = df[col]
        with duckdb_connection() as con, registered_view(con, "t", df) as view:
            q = quote_identifier(col)
            stats = query_df(
                con,
                f"""
                SELECT
                    COUNT(DISTINCT {q}) AS distinct_count,
                    COUNT(*) FILTER (WHERE {q} IS NULL) AS null_count,
                    MIN(TRY_CAST({q} AS DOUBLE)) AS min_value,
                    MAX(TRY_CAST({q} AS DOUBLE)) AS max_value,
                    AVG(TRY_CAST({q} AS DOUBLE)) AS mean_value,
                    MEDIAN(TRY_CAST({q} AS DOUBLE)) AS median_value,
                    STDDEV(TRY_CAST({q} AS DOUBLE)) AS stddev_value
                FROM {view}
                """,
            ).iloc[0]

        null_count = int(stats["null_count"])
        return {
            "column": col,
            "dtype": str(series.dtype),
            "distinct_count": int(stats["distinct_count"]),
            "null_count": null_count,
            "null_percent": round(null_count / total_rows * 100.0, 4) if total_rows else 0.0,
            "min": stats["min_value"],
            "max": stats["max_value"],
            "mean": stats["mean_value"],
            "median": stats["median_value"],
            "stddev": stats["stddev_value"],
            "semantic_type": cls._infer_semantic_type(series, stats["distinct_count"], total_rows),
        }

    @staticmethod
    def _infer_semantic_type(series: pd.Series, distinct_count: int, total_rows: int) -> str:
        if pd.api.types.is_bool_dtype(series):
            return "BOOLEAN"
        if pd.api.types.is_datetime64_any_dtype(series):
            return "DATE"
        if pd.api.types.is_numeric_dtype(series):
            if total_rows and distinct_count / total_rows > 0.95:
                return "NUMERIC_ID"
            return "NUMERIC"

        sample = series.dropna().astype(str).head(_SEMANTIC_SAMPLE_SIZE)
        if sample.empty:
            return "UNKNOWN"
        if (sample.str.match(_EMAIL_RE).mean()) >= _SEMANTIC_MATCH_THRESHOLD:
            return "EMAIL"
        if (sample.str.match(_PHONE_RE).mean()) >= _SEMANTIC_MATCH_THRESHOLD:
            return "PHONE"
        if total_rows and distinct_count / total_rows > 0.95:
            return "IDENTIFIER"
        return "FREE_TEXT"
