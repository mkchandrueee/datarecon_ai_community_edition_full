# datarecon/application/services/data_extraction_service.py  (NEW)
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from datarecon.domain.entities.column_catalog_metadata import ColumnCatalogMetadata
from datarecon.domain.enums import DatabaseType, FileFormat
from datarecon.domain.interfaces.connection_repository import IConnectionRepository
from datarecon.domain.interfaces.data_extractor import IDataExtractionService
from datarecon.infrastructure.extraction.data_extractor import (
    DataExtractor,
    ExtractionRequest,
)
from datarecon.infrastructure.security.crypto import CredentialCipher


class DataExtractionService(IDataExtractionService):
    """Service Layer: resolves the connection, decrypts the credential at the
    last responsible moment, and delegates to the infrastructure extractor."""

    def __init__(
        self,
        repository: IConnectionRepository,
        cipher: CredentialCipher,
        extractor: DataExtractor,
    ):
        self._repo = repository
        self._cipher = cipher
        self._extractor = extractor

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
    ) -> pd.DataFrame:
        conn = self._repo.get_by_id(connection_id)
        if conn is None:
            raise ValueError("Connection not found.")
        secret = self._cipher.decrypt(conn.password_encrypted) or ""
        request = ExtractionRequest(
            query=query,
            table=table,
            collection=collection,
            mongo_filter=mongo_filter,
            object_path=object_path,
            file_format=file_format,
            columns=columns,
            row_limit=row_limit,
            read_options=read_options or {},
        )
        df = self._extractor.extract(conn, request, secret)
        self._repo.increment_usage(connection_id)
        return df

    def get_table_catalog_metadata(
        self, connection_id: str, table: str
    ) -> list[ColumnCatalogMetadata] | None:
        conn = self._repo.get_by_id(connection_id)
        if conn is None:
            return None
        secret = self._cipher.decrypt(conn.password_encrypted) or ""
        return self._extractor.get_catalog_columns(conn, table, secret)

    def get_database_type(self, connection_id: str) -> DatabaseType | None:
        """The connection's dialect, for callers that must write SQL against it
        (identifier quoting differs between MySQL, SQL Server and the rest)."""
        conn = self._repo.get_by_id(connection_id)
        return conn.database_type if conn else None
