# datarecon/domain/entities/project.py
# A Project groups related Test Suites (see test_suite.py / ADR-0005).
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

DEFAULT_PROJECT_ID = "default"


@dataclass
class Project:
    name: str
    description: str = ""
    project_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)
