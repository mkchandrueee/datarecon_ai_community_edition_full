# datarecon/domain/entities/validation_run.py
"""Run-history record shared by every validation module (Modules 18/19/20).

Only summary metrics are persisted here — full row-level detail (mismatch
frames, duplicate samples, profile histograms) stays transient in the
Streamlit session for immediate display/export (Module 18) and is not
written to the metadata store. See ADR-0004.
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

    run_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))
