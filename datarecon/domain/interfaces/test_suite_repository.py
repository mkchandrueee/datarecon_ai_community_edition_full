# datarecon/domain/interfaces/test_suite_repository.py
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.enums import RunStatus


class ITestSuiteRepository(ABC):
    """Repository Pattern: abstract persistence contract for saved test suites."""

    @abstractmethod
    def add(self, suite: TestSuite) -> TestSuite: ...

    @abstractmethod
    def update(self, suite: TestSuite) -> TestSuite: ...

    @abstractmethod
    def delete(self, suite_id: str) -> bool: ...

    @abstractmethod
    def get_by_id(self, suite_id: str) -> TestSuite | None: ...

    @abstractmethod
    def list_all(self) -> list[TestSuite]: ...

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[TestSuite]: ...

    @abstractmethod
    def record_run_result(
        self, suite_id: str, run_id: str | None, status: RunStatus, when: datetime
    ) -> None: ...
