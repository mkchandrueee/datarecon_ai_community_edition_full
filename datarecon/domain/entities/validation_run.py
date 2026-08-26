# datarecon/domain/entities/validation_run.py
"""Run-history record shared by every validation module (Modules 18/19/20).

Only summary metrics are persisted here — full row-level detail (mismatch
frames, duplicate samples, profile histograms) is never written to this
metadata store (See ADR-0004), but is separately persisted per run_id in
the Parquet-backed RunDetailStore (see ADR-0008) so Module 18 can replay
it later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from datarecon.domain.entities.project import DEFAULT_PROJECT_ID
from datarecon.domain.enums import RunStatus, ValidationModule


@dataclass
class ValidationRun:
    module: ValidationModule
    name: str
    status: RunStatus
    summary: dict[str, Any] = field(default_factory=dict)
    source_connection_id: str | None = None
    target_connection_id: str | None = None
    error_message: str | None = None
    runtime_seconds: float = 0.0
    project_id: str = DEFAULT_PROJECT_ID
    suite_id: str | None = None  # set only when triggered by TestSuiteService.run_suite()
    #: Archived runs stay in history but drop out of Reports/Dashboard by
    #: default, so a superseded failure stops skewing the current picture.
    #: Archiving is always a deliberate act — nothing archives itself.
    archived: bool = False

    run_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))
