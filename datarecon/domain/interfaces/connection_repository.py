# datarecon/domain/interfaces/connection_repository.py
from __future__ import annotations

from abc import ABC, abstractmethod

from datarecon.domain.entities.connection import Connection


class IConnectionRepository(ABC):
    """Repository Pattern: abstract persistence contract for connections."""

    @abstractmethod
    def add(self, connection: Connection) -> Connection: ...

    @abstractmethod
    def update(self, connection: Connection) -> Connection: ...

    @abstractmethod
    def delete(self, connection_id: str) -> bool: ...

    @abstractmethod
    def get_by_id(self, connection_id: str) -> Connection | None: ...

    @abstractmethod
    def get_by_name(self, connection_name: str) -> Connection | None: ...

    @abstractmethod
    def list_all(self) -> list[Connection]: ...

    @abstractmethod
    def increment_usage(self, connection_id: str) -> None: ...

    @abstractmethod
    def record_test_result(self, connection_id: str, status: str) -> None: ...
