# datarecon/infrastructure/extraction/data_extractor.py  (NEW)
# Unified extraction layer (Task 2.1): pulls data from EVERY Module 1 source
# into a pandas DataFrame. Strategy-per-category; enforces the Community
# Edition 5M-record ceiling via chunked reads.
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import sqlalchemy
from sqlalchemy import text

from config.settings import settings
from datarecon.domain.entities.column_catalog_metadata import ColumnCatalogMetadata
from datarecon.domain.entities.connection import Connection
from datarecon.domain.entities.foreign_key_metadata import ForeignKeyMetadata
from datarecon.domain.enums import (
    ConnectionCategory,
    FileFormat,
    file_format_for,
    file_format_from_path,
)
from datarecon.infrastructure.connectors.dbapi_connector import DBAPIConnectorFactory
from datarecon.infrastructure.connectors.engine_factory import EngineFactory
from datarecon.infrastructure.connectors.mongodb_connector import MongoDBConnector
from datarecon.infrastructure.connectors.storage_client_factory import (
    StorageClientFactory,
)
from datarecon.infrastructure.extraction.file_readers import read_file

logger = logging.getLogger("datarecon.infrastructure.extraction")


class ExtractionError(Exception):
    """Raised when a source cannot be read into a DataFrame."""


@dataclass(frozen=True)
class ExtractionRequest:
    """One extraction unit of work against a saved connection."""

    query: str | None = None  # SQL text (SQL/ODBC/JDBC sources)
    table: str | None = None  # fallback: SELECT cols FROM table
    collection: str | None = None  # MongoDB collection
    mongo_filter: dict[str, Any] | None = None
    object_path: str | None = None  # overrides Connection.file_path
    file_format: FileFormat | None = None
    columns: Sequence[str] | None = None
    row_limit: int | None = None  # None -> edition ceiling
    chunk_size: int = 250_000
    read_options: dict[str, Any] = field(default_factory=dict)


class DataExtractor:
    """Routes an ExtractionRequest to the correct connector and returns a
    pandas DataFrame. Framework-agnostic; credentials arrive already
    decrypted from the application service."""

    def __init__(
        self,
        engine_factory: EngineFactory,
        dbapi_factory: DBAPIConnectorFactory | None = None,
        mongo_connector: MongoDBConnector | None = None,
        storage_factory: StorageClientFactory | None = None,
        max_records: int = settings.max_records_supported,
    ):
        self._engines = engine_factory
        self._dbapi = dbapi_factory or DBAPIConnectorFactory()
        self._mongo = mongo_connector or MongoDBConnector()
        self._storage = storage_factory or StorageClientFactory()
        self._max_records = max_records

    # ------------------------------------------------------------------ #
    def extract(
        self, conn: Connection, request: ExtractionRequest, secret: str = ""
    ) -> pd.DataFrame:
        limit = min(request.row_limit or self._max_records, self._max_records)
        category = conn.category
        logger.info(
            "Extracting from '%s' (%s / %s), limit=%d",
            conn.connection_name,
            category.value,
            conn.database_type.value,
            limit,
        )
        if category == ConnectionCategory.RELATIONAL:
            if self._engines.supports(conn.database_type):
                return self._from_sqlalchemy(conn, request, secret, limit)
            return self._from_dbapi(conn, request, secret, limit)  # Informix, IDMS
        if category == ConnectionCategory.GENERIC:
            return self._from_dbapi(conn, request, secret, limit)
        if category == ConnectionCategory.NOSQL:
            return self._from_mongodb(conn, request, secret, limit)
        if category == ConnectionCategory.STORAGE:
            return self._from_storage(conn, request, secret, limit)
        if category == ConnectionCategory.FILE:
            return self._from_local_file(conn, request, limit)
        raise ExtractionError(f"Unsupported category: {category}")

    # ------------------------------------------------------------------ #
    # Catalog metadata (Module 2 length/PK/default enrichment — ADR-0007)
    # ------------------------------------------------------------------ #
    def get_catalog_columns(
        self, conn: Connection, table: str, secret: str = ""
    ) -> list[ColumnCatalogMetadata] | None:
        """Native catalog metadata for a physical table via SQLAlchemy's
        Inspector. Returns None when the connection isn't a SQLAlchemy-backed
        relational one, the table can't be found, or inspection fails for
        any reason — callers fall back to DataFrame-inferred comparison."""
        if conn.category != ConnectionCategory.RELATIONAL or not self._engines.supports(
            conn.database_type
        ):
            return None
        schema, table_name = (table.split(".", 1) if "." in table else (None, table))
        schema = schema or conn.schema_name or None
        engine = self._engines.create(conn, secret)
        try:
            inspector = sqlalchemy.inspect(engine)
            if not inspector.has_table(table_name, schema=schema):
                return None
            pk_columns = set(
                inspector.get_pk_constraint(table_name, schema=schema).get(
                    "constrained_columns"
                )
                or []
            )
            columns = []
            for col in inspector.get_columns(table_name, schema=schema):
                col_type = col["type"]
                max_length = getattr(col_type, "length", None) or getattr(
                    col_type, "precision", None
                )
                default = col.get("default")
                columns.append(
                    ColumnCatalogMetadata(
                        name=col["name"],
                        native_type=str(col_type),
                        max_length=max_length,
                        nullable=bool(col.get("nullable", True)),
                        default=str(default) if default is not None else None,
                        is_primary_key=col["name"] in pk_columns,
                    )
                )
            return columns
        except Exception:
            logger.warning("Catalog inspection failed for table '%s'", table, exc_info=True)
            return None
        finally:
            engine.dispose()

    def get_foreign_keys(
        self, conn: Connection, table: str, secret: str = ""
    ) -> list[ForeignKeyMetadata] | None:
        """Foreign keys declared on a physical table (ADR-0012).

        Same availability rules as get_catalog_columns: SQLAlchemy-backed
        relational connections with a real table name. Returns None when the
        catalog can't be read, and an empty list when the table simply has no
        declared foreign keys — those mean different things to the caller.
        """
        if conn.category != ConnectionCategory.RELATIONAL or not self._engines.supports(
            conn.database_type
        ):
            return None
        schema, table_name = (table.split(".", 1) if "." in table else (None, table))
        schema = schema or conn.schema_name or None
        engine = self._engines.create(conn, secret)
        try:
            inspector = sqlalchemy.inspect(engine)
            if not inspector.has_table(table_name, schema=schema):
                return None
            return [
                ForeignKeyMetadata(
                    name=fk.get("name"),
                    columns=list(fk.get("constrained_columns") or []),
                    referred_table=fk.get("referred_table") or "",
                    referred_schema=fk.get("referred_schema"),
                    referred_columns=list(fk.get("referred_columns") or []),
                )
                for fk in inspector.get_foreign_keys(table_name, schema=schema)
                if fk.get("referred_table")
            ]
        except Exception:
            logger.warning("Foreign-key inspection failed for '%s'", table, exc_info=True)
            return None
        finally:
            engine.dispose()

    # ------------------------------------------------------------------ #
    # SQL sources
    # ------------------------------------------------------------------ #
    def _from_sqlalchemy(
        self, conn: Connection, req: ExtractionRequest, secret: str, limit: int
    ) -> pd.DataFrame:
        sql = self._resolve_sql(req)
        engine = self._engines.create(conn, secret)
        try:
            chunks, total = [], 0
            for chunk in pd.read_sql(text(sql), engine, chunksize=req.chunk_size):
                chunks.append(chunk)
                total += len(chunk)
                if total >= limit:
                    logger.warning("Row limit %d reached; extraction truncated.", limit)
                    break
            df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
            return df.iloc[:limit]
        finally:
            engine.dispose()

    def _from_dbapi(
        self, conn: Connection, req: ExtractionRequest, secret: str, limit: int
    ) -> pd.DataFrame:
        sql = self._resolve_sql(req)
        cxn = self._dbapi.create(conn, secret)
        try:
            cur = cxn.cursor()
            cur.execute(sql)
            columns = [d[0] for d in cur.description]
            rows, total = [], 0
            while total < limit:
                batch = cur.fetchmany(req.chunk_size)
                if not batch:
                    break
                rows.extend(batch)
                total += len(batch)
            cur.close()
            df = pd.DataFrame.from_records(rows[:limit], columns=columns)
            return df
        finally:
            cxn.close()

    @staticmethod
    def _resolve_sql(req: ExtractionRequest) -> str:
        if req.query:
            return req.query
        if req.table:
            cols = ", ".join(req.columns) if req.columns else "*"
            return f"SELECT {cols} FROM {req.table}"
        raise ExtractionError("A SQL query or table name is required.")

    # ------------------------------------------------------------------ #
    # MongoDB
    # ------------------------------------------------------------------ #
    def _from_mongodb(
        self, conn: Connection, req: ExtractionRequest, secret: str, limit: int
    ) -> pd.DataFrame:
        if not req.collection:
            raise ExtractionError("MongoDB extraction requires a collection name.")
        client = self._mongo.create_client(conn, secret)
        try:
            db = client[conn.database_name or "admin"]
            flt = req.mongo_filter or (json.loads(req.query) if req.query else {})
            projection = dict.fromkeys(req.columns, 1) if req.columns else None
            cursor = db[req.collection].find(flt, projection).limit(limit)
            docs = list(cursor)
            if not docs:
                return pd.DataFrame()
            df = pd.json_normalize(docs)
            if "_id" in df.columns:
                df["_id"] = df["_id"].astype(str)
            return df
        finally:
            client.close()

    # ------------------------------------------------------------------ #
    # Cloud storage objects
    # ------------------------------------------------------------------ #
    def _from_storage(
        self, conn: Connection, req: ExtractionRequest, secret: str, limit: int
    ) -> pd.DataFrame:
        key = req.object_path or conn.file_path
        if not key:
            raise ExtractionError("Storage extraction requires an object path.")
        fmt = self._resolve_format(conn, req, key)
        buf = self._storage.download_object(conn, key, secret)
        df = read_file(buf, fmt, req.read_options)
        return self._finalize(df, req, limit)

    # ------------------------------------------------------------------ #
    # Local files
    # ------------------------------------------------------------------ #
    def _from_local_file(
        self, conn: Connection, req: ExtractionRequest, limit: int
    ) -> pd.DataFrame:
        path = req.object_path or conn.file_path
        if not path:
            raise ExtractionError("File extraction requires a file path.")
        fmt = self._resolve_format(conn, req, path)
        df = read_file(path, fmt, req.read_options)
        return self._finalize(df, req, limit)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_format(conn: Connection, req: ExtractionRequest, path: str) -> FileFormat:
        fmt = (
            req.file_format
            or (FileFormat(conn.file_format) if conn.file_format else None)
            or file_format_for(conn.database_type)
            or file_format_from_path(path)
        )
        if fmt is None:
            raise ExtractionError(f"Cannot infer file format for '{path}'.")
        return fmt

    @staticmethod
    def _finalize(df: pd.DataFrame, req: ExtractionRequest, limit: int) -> pd.DataFrame:
        if req.columns:
            missing = [c for c in req.columns if c not in df.columns]
            if missing:
                raise ExtractionError(f"Columns not found in source: {missing}")
            df = df[list(req.columns)]
        if len(df) > limit:
            logger.warning("Row limit %d reached; extraction truncated.", limit)
            df = df.iloc[:limit]
        return df.reset_index(drop=True)
