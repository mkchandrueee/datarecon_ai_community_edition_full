# datarecon/domain/interfaces/project_repository.py
from __future__ import annotations

from abc import ABC, abstractmethod

from datarecon.domain.entities.project import Project


class IProjectRepository(ABC):
    """Repository Pattern: abstract persistence contract for projects."""

    @abstractmethod
    def add(self, project: Project) -> Project: ...

    @abstractmethod
    def update(self, project: Project) -> Project: ...

    @abstractmethod
    def delete(self, project_id: str) -> bool: ...

    @abstractmethod
    def get_by_id(self, project_id: str) -> Project | None: ...

    @abstractmethod
    def get_by_name(self, name: str) -> Project | None: ...

    @abstractmethod
    def list_all(self) -> list[Project]: ...
