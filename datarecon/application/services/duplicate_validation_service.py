# datarecon/application/services/duplicate_validation_service.py
# Module 4: Duplicate Validation.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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


class DuplicateValidationError(ValueError):
    """Raised for malformed duplicate-validation requests."""


@dataclass(frozen=True)
class DuplicateValidationRequest:
    connection_id: str
    key_columns: Sequence[str]
    query: str | None = None
    table: str | None = None
    sample_limit: int = 1000
    name: str = "Duplicate Validation"


@dataclass
class DuplicateValidationResult:
    total_rows: int
    duplicate_key_count: int
    duplicate_row_count: int
    duplicate_percent: float
    status: RunStatus
    duplicates: pd.DataFrame
    run: ValidationRun


class DuplicateValidationService:
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
        request: DuplicateValidationRequest,
        project_id: str = DEFAULT_PROJECT_ID,
        suite_id: str | None = None,
    ) -> DuplicateValidationResult:
        if not request.key_columns:
            raise DuplicateValidationError("At least one key column is required.")
        started = datetime.now(UTC)
        try:
            df = self._extraction.extract_dataframe(
                request.connection_id, query=request.query, table=request.table
            )
            total_rows, dup_key_count, dup_row_count, duplicates = self._analyze(
                df, list(request.key_columns), request.sample_limit
            )
            duplicate_percent = round(dup_row_count / total_rows * 100.0, 4) if total_rows else 0.0
            status = RunStatus.FAIL if dup_row_count > 0 else RunStatus.PASS

            run = record_run(
                self._runs,
                ValidationModule.DUPLICATE,
                request.name,
                started,
                status,
                source_connection_id=request.connection_id,
                summary={
                    "total_rows": total_rows,
                    "duplicate_key_count": dup_key_count,
                    "duplicate_row_count": dup_row_count,
                    "duplicate_percent": duplicate_percent,
                },
                project_id=project_id,
                suite_id=suite_id,
            )
            if not duplicates.empty:
                self._details.save(run.run_id, {"Duplicate Rows": duplicates})
            return DuplicateValidationResult(
                total_rows, dup_key_count, dup_row_count, duplicate_percent, status, duplicates, run
            )
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.DUPLICATE,
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
        df: pd.DataFrame, key_columns: list[str], sample_limit: int
    ) -> tuple[int, int, int, pd.DataFrame]:
        missing = [c for c in key_columns if c not in df.columns]
        if missing:
            raise DuplicateValidationError(f"Key column(s) not found: {missing}")

        with duckdb_connection() as con, registered_view(con, "src", df) as view:
            keys_sql = ", ".join(quote_identifier(c) for c in key_columns)
            total_rows = int(query_df(con, f"SELECT COUNT(*) AS n FROM {view}")["n"].iloc[0])

            dup_keys_sql = f"""
                SELECT {keys_sql}, COUNT(*) AS occurrence_count
                FROM {view}
                GROUP BY {keys_sql}
                HAVING COUNT(*) > 1
            """
            dup_keys = query_df(con, dup_keys_sql)
            dup_key_count = len(dup_keys)
            dup_row_count = int(dup_keys["occurrence_count"].sum()) if dup_key_count else 0

            duplicates = pd.DataFrame()
            if dup_key_count:
                sample_sql = f"""
                    SELECT s.*, d.occurrence_count
                    FROM {view} s
                    JOIN ({dup_keys_sql}) d USING ({keys_sql})
                    ORDER BY {keys_sql}
                    LIMIT {int(sample_limit)}
                """
                duplicates = query_df(con, sample_sql)

        return total_rows, dup_key_count, dup_row_count, duplicates
