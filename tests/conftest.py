"""Shared pytest fixtures for validation-module tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from datarecon.domain.entities.column_catalog_metadata import ColumnCatalogMetadata
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase
from datarecon.infrastructure.persistence.sqlite_project_repository import (
    SQLiteProjectRepository,
)
from datarecon.infrastructure.persistence.sqlite_test_suite_repository import (
    SQLiteTestSuiteRepository,
)
from datarecon.infrastructure.persistence.sqlite_validation_run_repository import (
    SQLiteValidationRunRepository,
)


class FakeExtractionService:
    """Stands in for DataExtractionService: returns a pre-registered DataFrame
    per connection_id instead of hitting a real connector."""

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        catalogs: dict[str, list[ColumnCatalogMetadata]] | None = None,
    ):
        self._frames = frames
        self._catalogs = catalogs or {}

    def extract_dataframe(self, connection_id: str, **_kwargs: Any) -> pd.DataFrame:
        if connection_id not in self._frames:
            raise ValueError(f"No fake frame registered for '{connection_id}'.")
        return self._frames[connection_id].copy()

    def get_table_catalog_metadata(
        self, connection_id: str, table: str
    ) -> list[ColumnCatalogMetadata] | None:
        return self._catalogs.get(f"{connection_id}:{table}")


@pytest.fixture
def metadata_db(tmp_path: Path) -> MetadataDatabase:
    return MetadataDatabase(tmp_path / "meta.db")


@pytest.fixture
def run_repository(metadata_db: MetadataDatabase) -> SQLiteValidationRunRepository:
    return SQLiteValidationRunRepository(metadata_db)


@pytest.fixture
def project_repository(metadata_db: MetadataDatabase) -> SQLiteProjectRepository:
    return SQLiteProjectRepository(metadata_db)


@pytest.fixture
def test_suite_repository(metadata_db: MetadataDatabase) -> SQLiteTestSuiteRepository:
    return SQLiteTestSuiteRepository(metadata_db)
