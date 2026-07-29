# datarecon/application/services/schema_validation_service.py
# Module 2: Schema Validation.
#
# The primary comparison (name/position/normalized type category) is still
# DataFrame-inferred, not native catalog metadata — see ADR-0001/0002. A
# small row sample is pulled (not the full dataset) since only dtypes are
# needed for that part.
#
# Length/key-column/default comparison (ADR-0007) is a second, additive
# layer: when a request names a physical table (not a custom SQL query)
# on a connection SQLAlchemy can inspect, native catalog metadata is
# pulled via DataExtractionService.get_table_catalog_metadata() and
# compared too. It degrades to "not evaluated" (None) per column when
# catalog metadata isn't available for both sides — the name/type/position
# comparison always runs regardless.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from datarecon.application.services.data_extraction_service import DataExtractionService
from datarecon.application.services.run_recording import record_run
from datarecon.domain.entities.column_catalog_metadata import ColumnCatalogMetadata
from datarecon.domain.entities.project import DEFAULT_PROJECT_ID
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository

_SCHEMA_SAMPLE_SIZE = 1000
_CRITICAL_STATUSES = frozenset({"MISSING_IN_TARGET", "EXTRA_IN_TARGET", "TYPE_MISMATCH"})


@dataclass(frozen=True)
class SchemaValidationRequest:
    source_connection_id: str
    target_connection_id: str
    source_query: str | None = None
    target_query: str | None = None
    source_table: str | None = None
    target_table: str | None = None
    name: str = "Schema Validation"


@dataclass
class SchemaValidationResult:
    status: RunStatus
    comparison: pd.DataFrame
    run: ValidationRun


def _dtype_category(dtype: object) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(dtype):
        return "INTEGER"
    if pd.api.types.is_float_dtype(dtype):
        return "FLOAT"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "DATETIME"
    if pd.api.types.is_object_dtype(dtype) or pd.api.types.is_string_dtype(dtype):
        return "STRING"
    return "OTHER"


class SchemaValidationService:
    def __init__(self, extraction: DataExtractionService, run_repository: IValidationRunRepository):
        self._extraction = extraction
        self._runs = run_repository

    def execute(
        self,
        request: SchemaValidationRequest,
        project_id: str = DEFAULT_PROJECT_ID,
        suite_id: str | None = None,
    ) -> SchemaValidationResult:
        started = datetime.now(UTC)
        try:
            source_df = self._extraction.extract_dataframe(
                request.source_connection_id,
                query=request.source_query,
                table=request.source_table,
                row_limit=_SCHEMA_SAMPLE_SIZE,
            )
            target_df = self._extraction.extract_dataframe(
                request.target_connection_id,
                query=request.target_query,
                table=request.target_table,
                row_limit=_SCHEMA_SAMPLE_SIZE,
            )
            source_catalog = (
                self._extraction.get_table_catalog_metadata(
                    request.source_connection_id, request.source_table
                )
                if not request.source_query and request.source_table
                else None
            )
            target_catalog = (
                self._extraction.get_table_catalog_metadata(
                    request.target_connection_id, request.target_table
                )
                if not request.target_query and request.target_table
                else None
            )
            comparison = self._compare_schemas(source_df, target_df, source_catalog, target_catalog)
            mismatches = int(comparison["status"].isin(_CRITICAL_STATUSES).sum())
            attribute_mismatch_mask = (
                comparison["length_match"].eq(False)
                | comparison["key_match"].eq(False)
                | comparison["default_match"].eq(False)
            )
            attribute_mismatches = int(attribute_mismatch_mask.sum())
            status = RunStatus.FAIL if (mismatches or attribute_mismatches) else RunStatus.PASS

            run = record_run(
                self._runs,
                ValidationModule.SCHEMA,
                request.name,
                started,
                status,
                source_connection_id=request.source_connection_id,
                target_connection_id=request.target_connection_id,
                summary={
                    "columns_compared": len(comparison),
                    "mismatches": mismatches,
                    "attribute_mismatches": attribute_mismatches,
                },
                project_id=project_id,
                suite_id=suite_id,
            )
            return SchemaValidationResult(status, comparison, run)
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.SCHEMA,
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
    def _compare_schemas(
        source_df: pd.DataFrame,
        target_df: pd.DataFrame,
        source_catalog: list[ColumnCatalogMetadata] | None = None,
        target_catalog: list[ColumnCatalogMetadata] | None = None,
    ) -> pd.DataFrame:
        source_positions = {c: i for i, c in enumerate(source_df.columns)}
        target_positions = {c: i for i, c in enumerate(target_df.columns)}
        all_columns = list(dict.fromkeys([*source_df.columns, *target_df.columns]))
        source_catalog_by_name = {c.name: c for c in source_catalog} if source_catalog else None
        target_catalog_by_name = {c.name: c for c in target_catalog} if target_catalog else None

        rows = []
        for col in all_columns:
            in_source = col in source_positions
            in_target = col in target_positions
            source_type = _dtype_category(source_df[col].dtype) if in_source else None
            target_type = _dtype_category(target_df[col].dtype) if in_target else None

            if not in_target:
                status = "MISSING_IN_TARGET"
            elif not in_source:
                status = "EXTRA_IN_TARGET"
            elif source_type != target_type:
                status = "TYPE_MISMATCH"
            elif source_positions[col] != target_positions[col]:
                status = "POSITION_MISMATCH"
            else:
                status = "MATCH"

            source_meta = source_catalog_by_name.get(col) if source_catalog_by_name else None
            target_meta = target_catalog_by_name.get(col) if target_catalog_by_name else None

            length_match = key_match = default_match = None
            if source_meta is not None and target_meta is not None:
                length_match = source_meta.max_length == target_meta.max_length
                key_match = source_meta.is_primary_key == target_meta.is_primary_key
                default_match = source_meta.default == target_meta.default

            rows.append(
                {
                    "column": col,
                    "source_position": source_positions.get(col),
                    "target_position": target_positions.get(col),
                    "source_type": source_type,
                    "target_type": target_type,
                    "status": status,
                    "source_length": source_meta.max_length if source_meta else None,
                    "target_length": target_meta.max_length if target_meta else None,
                    "length_match": length_match,
                    "source_key": source_meta.is_primary_key if source_meta else None,
                    "target_key": target_meta.is_primary_key if target_meta else None,
                    "key_match": key_match,
                    "source_default": source_meta.default if source_meta else None,
                    "target_default": target_meta.default if target_meta else None,
                    "default_match": default_match,
                }
            )
        return pd.DataFrame(rows)
