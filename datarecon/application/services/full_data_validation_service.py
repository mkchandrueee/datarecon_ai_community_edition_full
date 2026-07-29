# datarecon/application/services/full_data_validation_service.py  (NEW)
# Module 6 orchestration: extract Source SQL + Target SQL, run the vectorized
# ComparisonEngine, return the four-way split + summary, and persist a
# ValidationRun (ADR-0004) alongside the other modules.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from datarecon.application.services.data_extraction_service import DataExtractionService
from datarecon.application.services.run_recording import record_run
from datarecon.core.engine import ComparisonConfig, ComparisonEngine, ComparisonResult
from datarecon.domain.entities.project import DEFAULT_PROJECT_ID
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository


@dataclass(frozen=True)
class FullValidationRequest:
    source_connection_id: str
    target_connection_id: str
    business_keys: Sequence[str]
    source_query: str | None = None
    target_query: str | None = None
    source_table: str | None = None
    target_table: str | None = None
    config: ComparisonConfig | None = None
    name: str = "Full Data Validation"


@dataclass
class FullValidationOutcome:
    result: ComparisonResult
    run: ValidationRun


class FullDataValidationService:
    def __init__(
        self, extraction_service: DataExtractionService, run_repository: IValidationRunRepository
    ):
        self._extraction = extraction_service
        self._runs = run_repository

    def execute(
        self,
        request: FullValidationRequest,
        project_id: str = DEFAULT_PROJECT_ID,
        suite_id: str | None = None,
    ) -> FullValidationOutcome:
        started = datetime.now(UTC)
        try:
            source_df = self._extraction.extract_dataframe(
                request.source_connection_id,
                query=request.source_query,
                table=request.source_table,
            )
            target_df = self._extraction.extract_dataframe(
                request.target_connection_id,
                query=request.target_query,
                table=request.target_table,
            )
            engine = ComparisonEngine(
                business_keys=list(request.business_keys), config=request.config
            )
            result = engine.compare(source_df, target_df)
            finished = datetime.now(UTC)
            result.summary.update(
                execution_start=started.isoformat(),
                execution_end=finished.isoformat(),
                runtime_seconds=round((finished - started).total_seconds(), 3),
            )
            status = RunStatus.PASS if result.is_passed() else RunStatus.FAIL

            run = record_run(
                self._runs,
                ValidationModule.FULL_DATA,
                request.name,
                started,
                status,
                source_connection_id=request.source_connection_id,
                target_connection_id=request.target_connection_id,
                summary=result.summary,
                project_id=project_id,
                suite_id=suite_id,
            )
            return FullValidationOutcome(result, run)
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.FULL_DATA,
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
