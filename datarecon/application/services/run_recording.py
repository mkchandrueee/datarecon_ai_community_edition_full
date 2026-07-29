# datarecon/application/services/run_recording.py
# Shared ValidationRun bookkeeping used by every validation module service
# (ADR-0004: only summary metrics are persisted).
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from datarecon.domain.entities.project import DEFAULT_PROJECT_ID
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository


def record_run(
    run_repository: IValidationRunRepository,
    module: ValidationModule,
    name: str,
    started: datetime,
    status: RunStatus,
    source_connection_id: str | None = None,
    target_connection_id: str | None = None,
    summary: dict[str, Any] | None = None,
    error_message: str | None = None,
    project_id: str = DEFAULT_PROJECT_ID,
    suite_id: str | None = None,
) -> ValidationRun:
    finished = datetime.now(UTC)
    run = ValidationRun(
        module=module,
        name=name,
        status=status,
        summary=summary or {},
        source_connection_id=source_connection_id,
        target_connection_id=target_connection_id,
        error_message=error_message,
        runtime_seconds=round((finished - started).total_seconds(), 3),
        project_id=project_id,
        suite_id=suite_id,
        started_at=started,
        finished_at=finished,
    )
    run_repository.add(run)
    return run
