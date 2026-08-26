# datarecon/application/services/aggregation_validation_service.py
# Module 7: Aggregation Validation.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from datarecon.application.services.data_extraction_service import DataExtractionService
from datarecon.application.services.run_recording import record_run
from datarecon.core.column_matching import align_to_source, resolve, resolve_all
from datarecon.core.engine.duckdb_engine import (
    duckdb_connection,
    query_df,
    quote_identifier,
    registered_view,
)
from datarecon.domain.entities.project import DEFAULT_PROJECT_ID
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import AggregateFunction, RunStatus, ValidationModule
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository
from datarecon.infrastructure.persistence.run_detail_store import RunDetailStore


class AggregationValidationError(ValueError):
    """Raised for malformed aggregation-validation requests."""


@dataclass(frozen=True)
class AggregationSpec:
    column: str
    function: AggregateFunction
    alias: str | None = None

    def resolved_alias(self) -> str:
        return self.alias or f"{self.function.value}_{self.column}"


@dataclass(frozen=True)
class AggregationValidationRequest:
    source_connection_id: str
    target_connection_id: str
    aggregations: Sequence[AggregationSpec]
    source_query: str | None = None
    target_query: str | None = None
    source_table: str | None = None
    target_table: str | None = None
    group_by: Sequence[str] = field(default_factory=tuple)
    tolerance_percent: float = 0.0
    name: str = "Aggregation Validation"


@dataclass
class AggregationValidationResult:
    status: RunStatus
    comparison: pd.DataFrame
    run: ValidationRun


class AggregationValidationService:
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
        request: AggregationValidationRequest,
        project_id: str = DEFAULT_PROJECT_ID,
        suite_id: str | None = None,
    ) -> AggregationValidationResult:
        if not request.aggregations:
            raise AggregationValidationError("At least one aggregation is required.")
        started = datetime.now(UTC)
        try:
            source_df = self._extraction.extract_dataframe(
                request.source_connection_id, query=request.source_query, table=request.source_table
            )
            target_df = self._extraction.extract_dataframe(
                request.target_connection_id, query=request.target_query, table=request.target_table
            )
            # One agreed spelling per column before aggregating, so the
            # per-metric merge below lines up even when the two databases
            # disagree on identifier casing (ADR-0009).
            target_df = align_to_source(source_df, target_df)
            group_cols, missing_groups = resolve_all(list(request.group_by), source_df.columns)
            if missing_groups:
                raise AggregationValidationError(
                    f"Group-by column(s) not found: {missing_groups}"
                )
            comparison = pd.concat(
                [
                    self._compare_one(
                        source_df, target_df, group_cols, spec, request.tolerance_percent
                    )
                    for spec in request.aggregations
                ],
                ignore_index=True,
            )
            status = (
                RunStatus.FAIL if (comparison["status"] == RunStatus.FAIL).any() else RunStatus.PASS
            )

            run = record_run(
                self._runs,
                ValidationModule.AGGREGATION,
                request.name,
                started,
                status,
                source_connection_id=request.source_connection_id,
                target_connection_id=request.target_connection_id,
                summary={
                    "metrics_compared": int(comparison["metric"].nunique()),
                    "rows_compared": len(comparison),
                    "rows_failed": int((comparison["status"] == RunStatus.FAIL).sum()),
                },
                project_id=project_id,
                suite_id=suite_id,
            )
            self._details.save(run.run_id, {"Aggregation Comparison": comparison})
            return AggregationValidationResult(status, comparison, run)
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.AGGREGATION,
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

    def _compare_one(
        self,
        source_df: pd.DataFrame,
        target_df: pd.DataFrame,
        group_cols: list[str],
        spec: AggregationSpec,
        tolerance_percent: float,
    ) -> pd.DataFrame:
        alias = spec.resolved_alias()
        src_agg = self._compute_aggregate(source_df, group_cols, spec, alias)
        tgt_agg = self._compute_aggregate(target_df, group_cols, spec, alias)

        if group_cols:
            merged = src_agg.merge(
                tgt_agg, on=group_cols, how="outer", suffixes=("_source", "_target")
            )
        else:
            merged = pd.DataFrame(
                {f"{alias}_source": src_agg[alias], f"{alias}_target": tgt_agg[alias]}
            )

        merged["source_value"] = merged[f"{alias}_source"].fillna(0)
        merged["target_value"] = merged[f"{alias}_target"].fillna(0)
        merged["difference"] = merged["target_value"] - merged["source_value"]
        merged["variance_percent"] = merged.apply(
            lambda r: self._variance_percent(r["source_value"], r["difference"]), axis=1
        )
        merged["metric"] = alias
        merged["status"] = merged["variance_percent"].apply(
            lambda v: RunStatus.FAIL if v > tolerance_percent else RunStatus.PASS
        )
        return merged[
            [
                *group_cols,
                "metric",
                "source_value",
                "target_value",
                "difference",
                "variance_percent",
                "status",
            ]
        ]

    @staticmethod
    def _variance_percent(source_value: float, difference: float) -> float:
        if pd.isna(source_value) or source_value == 0:
            return 0.0 if not difference else 100.0
        return round(abs(difference) / abs(source_value) * 100.0, 4)

    @staticmethod
    def _compute_aggregate(
        df: pd.DataFrame, group_cols: list[str], spec: AggregationSpec, alias: str
    ) -> pd.DataFrame:
        # Both sides were aligned to the source's spelling by execute(), so a
        # name typed in any case resolves to the one the frames actually use.
        column = resolve(spec.column, df.columns)
        if column is None:
            raise AggregationValidationError(f"Aggregation column '{spec.column}' not found.")
        resolved_groups, missing_group = resolve_all(group_cols, df.columns)
        if missing_group:
            raise AggregationValidationError(f"Group-by column(s) not found: {missing_group}")

        with duckdb_connection() as con, registered_view(con, "t", df) as view:
            col_q = quote_identifier(column)
            if spec.function == AggregateFunction.COUNT_DISTINCT:
                expr = f"COUNT(DISTINCT {col_q})"
            elif spec.function == AggregateFunction.COUNT:
                expr = f"COUNT({col_q})"
            else:
                expr = f"{spec.function.value}({col_q})"
            group_select = ", ".join(quote_identifier(c) for c in resolved_groups)
            select_cols = (
                f"{group_select}, " if resolved_groups else ""
            ) + f"{expr} AS {quote_identifier(alias)}"
            group_clause = f" GROUP BY {group_select}" if resolved_groups else ""
            return query_df(con, f"SELECT {select_cols} FROM {view}{group_clause}")
