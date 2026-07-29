# datarecon/domain/interfaces/data_extractor.py  (NEW)
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

import pandas as pd

from datarecon.domain.entities.column_catalog_metadata import ColumnCatalogMetadata
from datarecon.domain.enums import FileFormat


class IDataExtractionService(ABC):
    """Application-facing contract: extract a saved connection into a DataFrame."""

    @abstractmethod
    def extract_dataframe(
        self,
        connection_id: str,
        query: str | None = None,
        table: str | None = None,
        collection: str | None = None,
        mongo_filter: dict[str, Any] | None = None,
        object_path: str | None = None,
        file_format: FileFormat | None = None,
        columns: Sequence[str] | None = None,
        row_limit: int | None = None,
        read_options: dict[str, Any] | None = None,
    ) -> pd.DataFrame: ...

    @abstractmethod
    def get_table_catalog_metadata(
        self, connection_id: str, table: str
    ) -> list[ColumnCatalogMetadata] | None:
        """Native DB catalog metadata (length/PK/default) for a table-backed
        relational connection, or None when unavailable (query-based
        extraction, unsupported connector, or inspection failure)."""
        ...
