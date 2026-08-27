# datarecon/application/services/referential_integrity_service.py
# Referential Integrity validation (ADR-0012).
#
# Checks that every child foreign-key value exists in the parent: the classic
# orphan check. This is deliberately *not* limited to declared constraints —
# the cases worth catching are usually exactly where the constraint isn't
# enforced: data landed from a file, replicated across databases, or loaded
# into a warehouse where FKs were dropped for load performance.
#
# Rows whose key is NULL are excluded rather than counted as orphans. SQL's
# referential rules treat a NULL foreign key as "no reference", not a broken
# one; whether that NULL is acceptable is Nullability Validation's question.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from datarecon.application.services.data_extraction_service import DataExtractionService
from datarecon.application.services.run_recording import record_run
from datarecon.core.column_matching import resolve_all
from datarecon.domain.entities.project import DEFAULT_PROJECT_ID
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository
from datarecon.infrastructure.persistence.run_detail_store import RunDetailStore


class ReferentialIntegrityError(ValueError):
    """Raised for malformed referential-integrity requests."""


@dataclass(frozen=True)
class ReferentialIntegrityRequest:
    #: Child (referencing) side.
    child_connection_id: str
    child_columns: Sequence[str]
    #: Parent (referenced) side. May live on a different connection entirely,
    #: which is the point for cross-database reconciliation.
    parent_connection_id: str
    parent_columns: Sequence[str]
    child_query: str | None = None
    child_table: str | None = None
    parent_query: str | None = None
    parent_table: str | None = None
    #: Orphan rate allowed before the run fails. 0.0 means any orphan fails.
    tolerance_percent: float = 0.0
    sample_limit: int = 1000
    name: str = "Referential Integrity"


@dataclass
class ReferentialIntegrityResult:
    child_rows: int
    checked_rows: int  # child rows with a non-null key
    null_key_rows: int
    orphan_rows: int
    orphan_percent: float
    distinct_orphan_keys: int
    status: RunStatus
    orphans: pd.DataFrame
    run: ValidationRun


class ReferentialIntegrityService:
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
        request: ReferentialIntegrityRequest,
        project_id: str = DEFAULT_PROJECT_ID,
        suite_id: str | None = None,
    ) -> ReferentialIntegrityResult:
        child_columns = list(request.child_columns)
        parent_columns = list(request.parent_columns)
        if not child_columns:
            raise ReferentialIntegrityError("At least one child key column is required.")
        if len(child_columns) != len(parent_columns):
            raise ReferentialIntegrityError(
                f"Child and parent key columns must pair up — got {len(child_columns)} "
                f"child and {len(parent_columns)} parent column(s)."
            )

        started = datetime.now(UTC)
        try:
            child_df = self._extraction.extract_dataframe(
                request.child_connection_id,
                query=request.child_query,
                table=request.child_table,
            )
            parent_df = self._extraction.extract_dataframe(
                request.parent_connection_id,
                query=request.parent_query,
                table=request.parent_table,
            )
            outcome = self._find_orphans(
                child_df, parent_df, child_columns, parent_columns, request.sample_limit
            )
            status = (
                RunStatus.PASS
                if outcome.orphan_percent <= request.tolerance_percent
                else RunStatus.FAIL
            )

            run = record_run(
                self._runs,
                ValidationModule.REFERENTIAL_INTEGRITY,
                request.name,
                started,
                status,
                source_connection_id=request.child_connection_id,
                target_connection_id=request.parent_connection_id,
                summary={
                    "child_rows": outcome.child_rows,
                    "checked_rows": outcome.checked_rows,
                    "null_key_rows": outcome.null_key_rows,
                    "orphan_rows": outcome.orphan_rows,
                    "orphan_percent": outcome.orphan_percent,
                    "distinct_orphan_keys": outcome.distinct_orphan_keys,
                },
                project_id=project_id,
                suite_id=suite_id,
            )
            if not outcome.orphans.empty:
                self._details.save(run.run_id, {"Orphan Rows": outcome.orphans})
            return ReferentialIntegrityResult(
                child_rows=outcome.child_rows,
                checked_rows=outcome.checked_rows,
                null_key_rows=outcome.null_key_rows,
                orphan_rows=outcome.orphan_rows,
                orphan_percent=outcome.orphan_percent,
                distinct_orphan_keys=outcome.distinct_orphan_keys,
                status=status,
                orphans=outcome.orphans,
                run=run,
            )
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.REFERENTIAL_INTEGRITY,
                request.name,
                started,
                RunStatus.ERROR,
                source_connection_id=request.child_connection_id,
                target_connection_id=request.parent_connection_id,
                error_message=str(exc),
                project_id=project_id,
                suite_id=suite_id,
            )
            raise

    # ------------------------------------------------------------------ #
    @dataclass
    class _Outcome:
        child_rows: int
        checked_rows: int
        null_key_rows: int
        orphan_rows: int
        orphan_percent: float
        distinct_orphan_keys: int
        orphans: pd.DataFrame

    def _find_orphans(
        self,
        child_df: pd.DataFrame,
        parent_df: pd.DataFrame,
        child_columns: list[str],
        parent_columns: list[str],
        sample_limit: int,
    ) -> _Outcome:
        # Names resolve case-insensitively (ADR-0009) so a key spelled
        # CUSTOMER_ID here and customer_id there still lines up.
        child_keys, missing_child = resolve_all(child_columns, child_df.columns)
        if missing_child:
            raise ReferentialIntegrityError(f"Child column(s) not found: {missing_child}")
        parent_keys, missing_parent = resolve_all(parent_columns, parent_df.columns)
        if missing_parent:
            raise ReferentialIntegrityError(f"Parent column(s) not found: {missing_parent}")

        child_rows = len(child_df)
        # A NULL foreign key is "no reference", not a broken one.
        with_key = child_df.dropna(subset=child_keys)
        checked_rows = len(with_key)
        null_key_rows = child_rows - checked_rows

        if checked_rows == 0:
            return self._Outcome(child_rows, 0, null_key_rows, 0, 0.0, 0, pd.DataFrame())

        # Parent keys are renamed to the child's spelling so the merge aligns
        # even when the two sides name the same column differently.
        parent_side = parent_df[parent_keys].drop_duplicates()
        parent_side.columns = child_keys
        parent_side = parent_side.dropna()

        merged = with_key.merge(
            parent_side, on=child_keys, how="left", indicator="_dr_match_"
        )
        orphan_mask = merged["_dr_match_"] == "left_only"
        orphans = merged.loc[orphan_mask].drop(columns=["_dr_match_"])

        orphan_rows = int(orphan_mask.sum())
        orphan_percent = round(orphan_rows / checked_rows * 100.0, 4)
        distinct_orphan_keys = len(orphans[child_keys].drop_duplicates())

        return self._Outcome(
            child_rows=child_rows,
            checked_rows=checked_rows,
            null_key_rows=null_key_rows,
            orphan_rows=orphan_rows,
            orphan_percent=orphan_percent,
            distinct_orphan_keys=distinct_orphan_keys,
            orphans=orphans.head(sample_limit).reset_index(drop=True),
        )
