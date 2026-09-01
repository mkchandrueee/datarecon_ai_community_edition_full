# datarecon/domain/entities/test_suite.py
# A Test Suite is a saved, named validation-module configuration (a
# serialized Request dataclass) that can be re-run later for regression
# checks. `schedule_cron` / `schedule_enabled` drive unattended execution by
# the scheduler process (ADR-0014); ADR-0005 reserved them for exactly this.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from datarecon.domain.enums import RunStatus, ValidationModule


@dataclass
class TestSuite:
    project_id: str
    name: str
    module: ValidationModule
    config: dict[str, Any]
    description: str = ""
    suite_id: str = field(default_factory=lambda: uuid4().hex)
    source_connection_id: str | None = None
    target_connection_id: str | None = None
    schedule_cron: str | None = None
    schedule_enabled: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_run_id: str | None = None
    last_run_status: RunStatus | None = None
    last_run_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)
