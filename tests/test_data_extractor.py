"""Unit tests — DataExtractor (Module 1 unified extraction layer).

RELATIONAL and FILE categories are exercised against real SQLite/CSV
data (no external service needed). GENERIC/DBAPI, NOSQL, and STORAGE are
exercised with injected fakes standing in for pyodbc/pymongo/boto3-style
clients, since DataExtractor already accepts those as constructor
dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import create_engine

from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import ConnectionRole, DatabaseType, FileFormat
from datarecon.infrastructure.connectors.engine_factory import EngineFactory
from datarecon.infrastructure.extraction.data_extractor import (
    DataExtractor,
    ExtractionError,
    ExtractionRequest,
)


# --------------------------------------------------------------------------- #
# RELATIONAL (real SQLite)
# --------------------------------------------------------------------------- #
@pytest.fixture
def sqlite_conn(tmp_path: Path) -> Connection:
    db_path = tmp_path / "src.db"
    engine = create_engine(f"sqlite:///{db_path}")
    pd.DataFrame({"id": range(10), "name": [f"row{i}" for i in range(10)]}).to_sql(
        "people", engine, index=False
    )
    engine.dispose()
    return Connection(
        connection_name="sqlite-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.SQLITE,
        file_path=str(db_path),
    )


@pytest.fixture
def extractor() -> DataExtractor:
    return DataExtractor(EngineFactory(), max_records=1000)


def test_extract_from_sqlite_table(extractor: DataExtractor, sqlite_conn: Connection) -> None:
    df = extractor.extract(sqlite_conn, ExtractionRequest(table="people"))
    assert len(df) == 10
    assert set(df.columns) == {"id", "name"}


def test_extract_from_sqlite_query(extractor: DataExtractor, sqlite_conn: Connection) -> None:
    df = extractor.extract(
        sqlite_conn, ExtractionRequest(query="SELECT id FROM people WHERE id < 3")
    )
    assert list(df["id"]) == [0, 1, 2]


def test_extract_respects_row_limit(extractor: DataExtractor, sqlite_conn: Connection) -> None:
    df = extractor.extract(sqlite_conn, ExtractionRequest(table="people", row_limit=4))
    assert len(df) == 4


def test_extract_row_limit_capped_by_max_records(sqlite_conn: Connection) -> None:
    small_extractor = DataExtractor(EngineFactory(), max_records=3)
    df = small_extractor.extract(sqlite_conn, ExtractionRequest(table="people", row_limit=100))
    assert len(df) == 3


def test_resolve_sql_requires_query_or_table(
    extractor: DataExtractor, sqlite_conn: Connection
) -> None:
    with pytest.raises(ExtractionError, match="query or table"):
        extractor.extract(sqlite_conn, ExtractionRequest())


def test_unsupported_category_raises(extractor: DataExtractor) -> None:
    conn = Connection(
        connection_name="odbc",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.ODBC,
        driver="some-dsn",
    )
    with pytest.raises(Exception):  # noqa: B017 - routes to DBAPI, fails without a real driver
        extractor.extract(conn, ExtractionRequest(query="SELECT 1"))


# --------------------------------------------------------------------------- #
# FILE (real local CSV)
# --------------------------------------------------------------------------- #
def test_extract_from_local_csv(extractor: DataExtractor, tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("id,name\n1,alice\n2,bob\n3,carol\n")
    conn = Connection(
        connection_name="csv-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
        file_path=str(path),
    )
    df = extractor.extract(conn, ExtractionRequest())
    assert len(df) == 3
    assert list(df.columns) == ["id", "name"]


def test_extract_from_local_file_column_projection(
    extractor: DataExtractor, tmp_path: Path
) -> None:
    path = tmp_path / "data.csv"
    path.write_text("id,name,extra\n1,alice,x\n")
    conn = Connection(
        connection_name="csv-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
        file_path=str(path),
    )
    df = extractor.extract(conn, ExtractionRequest(columns=["id", "name"]))
    assert list(df.columns) == ["id", "name"]


def test_extract_missing_projected_column_raises(extractor: DataExtractor, tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("id\n1\n")
    conn = Connection(
        connection_name="csv-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
        file_path=str(path),
    )
    with pytest.raises(ExtractionError, match="not found in source"):
        extractor.extract(conn, ExtractionRequest(columns=["does_not_exist"]))


def test_extract_local_file_requires_path(extractor: DataExtractor) -> None:
    conn = Connection(
        connection_name="csv-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
        file_path=None,
    )
    with pytest.raises(ExtractionError, match="file path"):
        extractor.extract(conn, ExtractionRequest())


def test_extract_infers_format_from_extension(extractor: DataExtractor, tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text('[{"id": 1}]')
    conn = Connection(
        connection_name="unspecified",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.JSON,
        file_path=str(path),
    )
    df = extractor.extract(conn, ExtractionRequest())
    assert df.iloc[0]["id"] == 1


def test_extract_row_limit_truncates_file_source(extractor: DataExtractor, tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("id\n" + "\n".join(str(i) for i in range(20)))
    conn = Connection(
        connection_name="csv-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
        file_path=str(path),
    )
    df = extractor.extract(conn, ExtractionRequest(row_limit=5))
    assert len(df) == 5


# --------------------------------------------------------------------------- #
# GENERIC / DBAPI (fake driver)
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, rows: list[tuple], columns: list[str]):
        self._rows = rows
        self.description = [(c,) for c in columns]
        self._fetched = False

    def execute(self, sql: str) -> None:
        pass

    def fetchmany(self, n: int) -> list[tuple]:
        if self._fetched:
            return []
        self._fetched = True
        return self._rows

    def close(self) -> None:
        pass


class _FakeDbapiConnection:
    def __init__(self, rows: list[tuple], columns: list[str]):
        self._rows = rows
        self._columns = columns
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows, self._columns)

    def close(self) -> None:
        self.closed = True


class _FakeDbapiFactory:
    def __init__(self, rows: list[tuple], columns: list[str]):
        self._rows = rows
        self._columns = columns
        self.last_connection: _FakeDbapiConnection | None = None

    def create(self, conn: Connection, secret: str) -> _FakeDbapiConnection:
        self.last_connection = _FakeDbapiConnection(self._rows, self._columns)
        return self.last_connection


def test_extract_generic_odbc_uses_dbapi_factory() -> None:
    fake_factory = _FakeDbapiFactory(rows=[(1, "a"), (2, "b")], columns=["id", "name"])
    extractor = DataExtractor(EngineFactory(), dbapi_factory=fake_factory, max_records=1000)
    conn = Connection(
        connection_name="odbc-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.ODBC,
        driver="some-dsn",
    )
    df = extractor.extract(conn, ExtractionRequest(query="SELECT * FROM t"))
    assert len(df) == 2
    assert list(df.columns) == ["id", "name"]
    assert fake_factory.last_connection is not None
    assert fake_factory.last_connection.closed is True


# --------------------------------------------------------------------------- #
# NOSQL / MongoDB (fake client)
# --------------------------------------------------------------------------- #
class _FakeMongoCursor:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    def limit(self, n: int) -> _FakeMongoCursor:
        return _FakeMongoCursor(self._docs[:n])

    def __iter__(self):
        return iter(self._docs)


class _FakeMongoCollection:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    def find(self, flt: dict, projection: dict | None) -> _FakeMongoCursor:
        return _FakeMongoCursor(self._docs)


class _FakeMongoDatabase:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    def __getitem__(self, name: str) -> _FakeMongoCollection:
        return _FakeMongoCollection(self._docs)


class _FakeMongoClient:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs
        self.closed = False

    def __getitem__(self, name: str) -> _FakeMongoDatabase:
        return _FakeMongoDatabase(self._docs)

    def close(self) -> None:
        self.closed = True


class _FakeMongoConnector:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs
        self.last_client: _FakeMongoClient | None = None

    def create_client(self, conn: Connection, secret: str) -> _FakeMongoClient:
        self.last_client = _FakeMongoClient(self._docs)
        return self.last_client


def test_extract_mongodb_uses_mongo_connector() -> None:
    fake_connector = _FakeMongoConnector(
        docs=[{"_id": 1, "name": "alice"}, {"_id": 2, "name": "bob"}]
    )
    extractor = DataExtractor(EngineFactory(), mongo_connector=fake_connector, max_records=1000)
    conn = Connection(
        connection_name="mongo-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.MONGODB,
        host="localhost",
        database_name="db",
    )
    df = extractor.extract(conn, ExtractionRequest(collection="people"))
    assert len(df) == 2
    assert df["_id"].dtype == object  # coerced to str
    assert fake_connector.last_client is not None
    assert fake_connector.last_client.closed is True


def test_extract_mongodb_requires_collection() -> None:
    fake_connector = _FakeMongoConnector(docs=[])
    extractor = DataExtractor(EngineFactory(), mongo_connector=fake_connector, max_records=1000)
    conn = Connection(
        connection_name="mongo-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.MONGODB,
        host="localhost",
    )
    with pytest.raises(ExtractionError, match="collection"):
        extractor.extract(conn, ExtractionRequest())


def test_extract_mongodb_empty_result() -> None:
    fake_connector = _FakeMongoConnector(docs=[])
    extractor = DataExtractor(EngineFactory(), mongo_connector=fake_connector, max_records=1000)
    conn = Connection(
        connection_name="mongo-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.MONGODB,
        host="localhost",
    )
    df = extractor.extract(conn, ExtractionRequest(collection="people"))
    assert df.empty


# --------------------------------------------------------------------------- #
# STORAGE (fake client)
# --------------------------------------------------------------------------- #
class _FakeStorageFactory:
    def __init__(self, content: bytes):
        self._content = content

    def download_object(self, conn: Connection, key: str, secret: str):
        from io import BytesIO

        return BytesIO(self._content)


def test_extract_storage_uses_storage_factory() -> None:
    fake_storage = _FakeStorageFactory(content=b"id,name\n1,alice\n")
    extractor = DataExtractor(EngineFactory(), storage_factory=fake_storage, max_records=1000)
    conn = Connection(
        connection_name="s3-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.AWS_S3,
        bucket="my-bucket",
        file_path="data.csv",
    )
    df = extractor.extract(conn, ExtractionRequest(file_format=FileFormat.CSV))
    assert len(df) == 1
    assert df.iloc[0]["name"] == "alice"


def test_extract_storage_requires_object_path() -> None:
    fake_storage = _FakeStorageFactory(content=b"")
    extractor = DataExtractor(EngineFactory(), storage_factory=fake_storage, max_records=1000)
    conn = Connection(
        connection_name="s3-src",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.AWS_S3,
        bucket="my-bucket",
    )
    with pytest.raises(ExtractionError, match="object path"):
        extractor.extract(conn, ExtractionRequest())
