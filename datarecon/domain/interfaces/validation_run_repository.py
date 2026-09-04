# datarecon/domain/interfaces/validation_run_repository.py
from __future__ import annotations

from abc import ABC, abstractmethod

from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import ValidationModule


class IValidationRunRepository(ABC):
    """Repository Pattern: abstract persistence contract for run history."""

    @abstractmethod
    def add(self, run: ValidationRun) -> ValidationRun: ...

    @abstractmethod
    def get_by_id(self, run_id: str) -> ValidationRun | None: ...

    @abstractmethod
    def list_recent(self, limit: int = 200) -> list[ValidationRun]: ...

    @abstractmethod
    def list_by_module(self, module: ValidationModule, limit: int = 200) -> list[ValidationRun]: ...

    @abstractmethod
    def list_by_project(self, project_id: str, limit: int = 200) -> list[ValidationRun]: ...

    @abstractmethod
    def set_archived(self, run_id: str, archived: bool) -> bool:
        """Archive or restore a run. False if no such run."""

    @abstractmethod
    def delete(self, run_id: str) -> bool:
        """Permanently remove a run. False if no such run."""

    @abstractmethod
    def list_filtered(
        self,
        project_id: str | None = None,
        module: ValidationModule | None = None,
        suite_id: str | None = None,
        limit: int = 200,
        include_archived: bool = False,
    ) -> list[ValidationRun]: ...
