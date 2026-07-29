"""Unit tests — EngineFactory (Module 1 connectivity matrix)."""

from __future__ import annotations

import pytest

from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import ConnectionRole, DatabaseType
from datarecon.infrastructure.connectors.engine_factory import (
    EngineFactory,
    UnsupportedEngineError,
)


@pytest.fixture
def factory() -> EngineFactory:
    return EngineFactory()


def _conn(db_type: DatabaseType, **overrides) -> Connection:
    defaults = {
        "connection_name": "test",
        "connection_role": ConnectionRole.SOURCE,
        "database_type": db_type,
        "host": "db.example.com",
        "database_name": "mydb",
        "username": "alice",
    }
    defaults.update(overrides)
    return Connection(**defaults)


@pytest.mark.parametrize(
    "db_type",
    [
        DatabaseType.POSTGRESQL,
        DatabaseType.GREENPLUM,
        DatabaseType.MYSQL,
        DatabaseType.MARIADB,
        DatabaseType.SQLSERVER,
        DatabaseType.SYNAPSE,
        DatabaseType.AZURE_SQL,
        DatabaseType.ORACLE,
        DatabaseType.SNOWFLAKE,
        DatabaseType.DB2,
        DatabaseType.TERADATA,
        DatabaseType.REDSHIFT,
        DatabaseType.DATABRICKS,
        DatabaseType.HIVE,
        DatabaseType.SPARK,
        DatabaseType.SAP_HANA,
        DatabaseType.SQLITE,
    ],
)
def test_supports_every_sqlalchemy_managed_type(
    factory: EngineFactory, db_type: DatabaseType
) -> None:
    assert factory.supports(db_type) is True


@pytest.mark.parametrize(
    "db_type",
    [DatabaseType.MONGODB, DatabaseType.ODBC, DatabaseType.JDBC, DatabaseType.CSV],
)
def test_does_not_support_non_sqlalchemy_types(
    factory: EngineFactory, db_type: DatabaseType
) -> None:
    assert factory.supports(db_type) is False


def test_create_raises_for_unsupported_type(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.MONGODB)
    with pytest.raises(UnsupportedEngineError):
        factory.create(conn, "secret")


def test_sqlite_requires_file_path(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.SQLITE, host=None, database_name=None, username=None, file_path=None)
    with pytest.raises(ValueError, match="file path"):
        factory.create(conn, "")


def test_sqlite_engine_points_at_file(factory: EngineFactory, tmp_path) -> None:
    db_file = tmp_path / "sample.db"
    conn = _conn(
        DatabaseType.SQLITE,
        host=None,
        database_name=None,
        username=None,
        file_path=str(db_file),
    )
    engine = factory.create(conn, "")
    try:
        assert engine.url.drivername == "sqlite"
        assert str(db_file) in str(engine.url.database)
    finally:
        engine.dispose()


def test_postgresql_engine_uses_default_port(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.POSTGRESQL, port=None)
    engine = factory.create(conn, "s3cr3t")
    try:
        assert engine.url.drivername == "postgresql+psycopg2"
        assert engine.url.port == 5432
        assert engine.url.host == "db.example.com"
        assert engine.url.database == "mydb"
        assert engine.url.username == "alice"
        assert engine.url.password == "s3cr3t"
    finally:
        engine.dispose()


def test_greenplum_reuses_postgres_wire_protocol(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.GREENPLUM, port=None)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "postgresql+psycopg2"
        assert engine.url.port == 5432
    finally:
        engine.dispose()


def test_explicit_port_overrides_default(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.POSTGRESQL, port=6543)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.port == 6543
    finally:
        engine.dispose()


def test_mysql_engine_url(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.MYSQL, port=None)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "mysql+pymysql"
        assert engine.url.port == 3306
    finally:
        engine.dispose()


def test_mariadb_engine_url_sets_charset(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.MARIADB, port=None)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "mariadb+pymysql"
        assert engine.url.query.get("charset") == "utf8mb4"
    finally:
        engine.dispose()


def test_sqlserver_default_driver_and_encrypt_flag(factory: EngineFactory) -> None:
    pytest.importorskip(
        "pyodbc", reason="requires the unixODBC system library", exc_type=ImportError
    )
    conn = _conn(DatabaseType.SQLSERVER, port=None)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "mssql+pyodbc"
        assert engine.url.port == 1433
        assert engine.url.query["driver"] == "ODBC Driver 18 for SQL Server"
        assert "Encrypt" not in engine.url.query
    finally:
        engine.dispose()


def test_azure_sql_forces_encrypt(factory: EngineFactory) -> None:
    pytest.importorskip(
        "pyodbc", reason="requires the unixODBC system library", exc_type=ImportError
    )
    conn = _conn(DatabaseType.AZURE_SQL, port=None)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.query.get("Encrypt") == "yes"
    finally:
        engine.dispose()


def test_oracle_uses_service_name(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.ORACLE, port=None, database_name="ORCLPDB1")
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "oracle+oracledb"
        assert engine.url.port == 1521
        assert engine.url.query.get("service_name") == "ORCLPDB1"
    finally:
        engine.dispose()


def test_snowflake_requires_account(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.SNOWFLAKE, account=None)
    with pytest.raises(ValueError, match="account"):
        factory.create(conn, "pw")


def test_snowflake_engine_url(factory: EngineFactory) -> None:
    pytest.importorskip("snowflake.sqlalchemy", reason="optional 'warehouse' extra")
    conn = _conn(
        DatabaseType.SNOWFLAKE,
        host=None,
        account="orgname-accountname",
        schema_name="PUBLIC",
        warehouse="WH_XS",
        role="SYSADMIN",
    )
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "snowflake"
        assert engine.url.host == "orgname-accountname"
        assert engine.url.query.get("warehouse") == "WH_XS"
        assert engine.url.query.get("role") == "SYSADMIN"
    finally:
        engine.dispose()


def test_databricks_requires_http_path(factory: EngineFactory) -> None:
    conn = _conn(DatabaseType.DATABRICKS, http_path=None)
    with pytest.raises(ValueError, match="HTTP Path"):
        factory.create(conn, "pw")


def test_databricks_engine_uses_token_auth(factory: EngineFactory) -> None:
    pytest.importorskip("databricks.sqlalchemy", reason="optional 'warehouse' extra")
    conn = _conn(DatabaseType.DATABRICKS, http_path="/sql/1.0/warehouses/abc123")
    engine = factory.create(conn, "dapiXXXX")
    try:
        assert engine.url.drivername == "databricks"
        assert engine.url.username == "token"
        assert engine.url.password == "dapiXXXX"
        assert engine.url.query.get("http_path") == "/sql/1.0/warehouses/abc123"
    finally:
        engine.dispose()


def test_db2_engine_url(factory: EngineFactory) -> None:
    pytest.importorskip("ibm_db_sa", reason="optional 'warehouse' extra")
    conn = _conn(DatabaseType.DB2, port=None)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "db2+ibm_db"
        assert engine.url.port == 50000
    finally:
        engine.dispose()


def test_teradata_engine_url(factory: EngineFactory) -> None:
    pytest.importorskip("teradatasqlalchemy", reason="optional 'warehouse' extra")
    conn = _conn(DatabaseType.TERADATA, port=1025, database_name="mydb")
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "teradatasql"
        assert engine.url.query.get("database") == "mydb"
        assert engine.url.query.get("dbs_port") == "1025"
    finally:
        engine.dispose()


def test_redshift_engine_url(factory: EngineFactory) -> None:
    pytest.importorskip("redshift_connector", reason="optional 'warehouse' extra")
    conn = _conn(DatabaseType.REDSHIFT, port=None)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "redshift+redshift_connector"
        assert engine.url.port == 5439
    finally:
        engine.dispose()


def test_hive_engine_url(factory: EngineFactory) -> None:
    pytest.importorskip("pyhive", reason="optional 'bigdata' extra")
    conn = _conn(DatabaseType.HIVE, port=None, database_name="default")
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "hive"
        assert engine.url.port == 10000
    finally:
        engine.dispose()


def test_spark_reuses_hive_dialect(factory: EngineFactory) -> None:
    pytest.importorskip("pyhive", reason="optional 'bigdata' extra")
    conn = _conn(DatabaseType.SPARK, port=None, database_name="default")
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "hive"
        assert engine.url.port == 10000
    finally:
        engine.dispose()


def test_sap_hana_engine_url(factory: EngineFactory) -> None:
    pytest.importorskip("sqlalchemy_hana", reason="optional 'warehouse' extra")
    conn = _conn(DatabaseType.SAP_HANA, port=None)
    engine = factory.create(conn, "pw")
    try:
        assert engine.url.drivername == "hana+hdbcli"
        assert engine.url.port == 30015
    finally:
        engine.dispose()


def test_test_static_method_runs_select_1(factory: EngineFactory, tmp_path) -> None:
    conn = _conn(
        DatabaseType.SQLITE,
        host=None,
        database_name=None,
        username=None,
        file_path=str(tmp_path / "probe.db"),
    )
    engine = factory.create(conn, "")
    try:
        EngineFactory.test(engine, DatabaseType.SQLITE)  # must not raise
    finally:
        engine.dispose()
