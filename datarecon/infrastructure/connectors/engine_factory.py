# datarecon/infrastructure/connectors/engine_factory.py  (MODIFIED — full PRD DB matrix)
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

from config.settings import settings
from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import DatabaseType

_DEFAULT_PORTS: dict[DatabaseType, int] = {
    DatabaseType.POSTGRESQL: 5432,
    DatabaseType.GREENPLUM: 5432,
    DatabaseType.MYSQL: 3306,
    DatabaseType.MARIADB: 3306,
    DatabaseType.SQLSERVER: 1433,
    DatabaseType.SYNAPSE: 1433,
    DatabaseType.AZURE_SQL: 1433,
    DatabaseType.ORACLE: 1521,
    DatabaseType.DB2: 50000,
    DatabaseType.TERADATA: 1025,
    DatabaseType.REDSHIFT: 5439,
    DatabaseType.DATABRICKS: 443,
    DatabaseType.HIVE: 10000,
    DatabaseType.SPARK: 10000,  # Spark Thrift Server (HiveServer2 protocol)
    DatabaseType.SAP_HANA: 30015,
}

_TEST_QUERIES: dict[DatabaseType, str] = {
    DatabaseType.ORACLE: "SELECT 1 FROM DUAL",
    DatabaseType.DB2: "SELECT 1 FROM SYSIBM.SYSDUMMY1",
    DatabaseType.SAP_HANA: "SELECT 1 FROM DUMMY",
}
_DEFAULT_TEST_QUERY = "SELECT 1"


class UnsupportedEngineError(ValueError):
    """Raised for types not served by SQLAlchemy (routed to DBAPI/storage/file
    connectors in the extraction layer)."""


class EngineFactory:
    """Factory + Strategy: builds SQLAlchemy engines per database type using
    URL.create so credentials are never string-interpolated (injection-safe,
    special characters handled). Non-SQLAlchemy sources (MongoDB, storage,
    files, ODBC/JDBC generic, Informix, IDMS) are served by dedicated
    connectors in datarecon/infrastructure/extraction."""

    def __init__(self, connect_timeout: int = settings.connect_timeout_seconds):
        self._timeout = connect_timeout
        self._builders: dict[DatabaseType, Callable[[Connection, str], Engine]] = {
            DatabaseType.SQLITE: self._sqlite,
            DatabaseType.POSTGRESQL: self._postgresql,
            DatabaseType.GREENPLUM: self._postgresql,  # PG wire protocol
            DatabaseType.MYSQL: self._mysql,
            DatabaseType.MARIADB: self._mariadb,
            DatabaseType.SQLSERVER: self._sqlserver,
            DatabaseType.SYNAPSE: self._sqlserver,  # T-SQL over ODBC 18
            DatabaseType.AZURE_SQL: self._sqlserver,
            DatabaseType.ORACLE: self._oracle,
            DatabaseType.SNOWFLAKE: self._snowflake,
            DatabaseType.DB2: self._db2,
            DatabaseType.TERADATA: self._teradata,
            DatabaseType.REDSHIFT: self._redshift,
            DatabaseType.DATABRICKS: self._databricks,
            DatabaseType.HIVE: self._hive,
            DatabaseType.SPARK: self._hive,  # Spark Thrift == HS2 dialect
            DatabaseType.SAP_HANA: self._sap_hana,
        }

    def supports(self, db_type: DatabaseType) -> bool:
        return db_type in self._builders

    def create(self, conn: Connection, plaintext_password: str = "") -> Engine:
        builder = self._builders.get(conn.database_type)
        if builder is None:
            raise UnsupportedEngineError(
                f"{conn.database_type.value} is not a SQLAlchemy-managed source; "
                f"use the DataExtractionService connector path."
            )
        return builder(conn, plaintext_password)

    @staticmethod
    def test(engine: Engine, db_type: DatabaseType) -> None:
        """Raises on failure; caller maps to Pass/Fail."""
        query = _TEST_QUERIES.get(db_type, _DEFAULT_TEST_QUERY)
        with engine.connect() as cxn:
            cxn.execute(text(query))

    # ---------- helpers ----------
    def _port(self, c: Connection) -> int:
        return c.port or _DEFAULT_PORTS[c.database_type]

    # ---------- builders ----------
    def _sqlite(self, c: Connection, _: str) -> Engine:
        if not c.file_path:
            raise ValueError("SQLite connection requires a file path.")
        return create_engine(f"sqlite:///{c.file_path}", pool_pre_ping=True)

    def _postgresql(self, c: Connection, pwd: str) -> Engine:
        url = URL.create(
            "postgresql+psycopg2",
            username=c.username,
            password=pwd,
            host=c.host,
            port=self._port(c),
            database=c.database_name,
        )
        return create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": self._timeout},
        )

    def _mysql(self, c: Connection, pwd: str) -> Engine:
        url = URL.create(
            "mysql+pymysql",
            username=c.username,
            password=pwd,
            host=c.host,
            port=self._port(c),
            database=c.database_name,
        )
        return create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": self._timeout},
        )

    def _mariadb(self, c: Connection, pwd: str) -> Engine:
        url = URL.create(
            "mariadb+pymysql",
            username=c.username,
            password=pwd,
            host=c.host,
            port=self._port(c),
            database=c.database_name,
            query={"charset": "utf8mb4"},
        )
        return create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": self._timeout},
        )

    def _sqlserver(self, c: Connection, pwd: str) -> Engine:
        query = {
            "driver": c.driver or "ODBC Driver 18 for SQL Server",
            "TrustServerCertificate": "yes",
            "timeout": str(self._timeout),
        }
        if c.database_type in (DatabaseType.SYNAPSE, DatabaseType.AZURE_SQL):
            query["Encrypt"] = "yes"
        url = URL.create(
            "mssql+pyodbc",
            username=c.username,
            password=pwd,
            host=c.host,
            port=self._port(c),
            database=c.database_name,
            query=query,
        )
        return create_engine(url, pool_pre_ping=True)

    def _oracle(self, c: Connection, pwd: str) -> Engine:
        url = URL.create(
            "oracle+oracledb",
            username=c.username,
            password=pwd,
            host=c.host,
            port=self._port(c),
            query={"service_name": c.database_name or ""},
        )
        return create_engine(url, pool_pre_ping=True)

    def _snowflake(self, c: Connection, pwd: str) -> Engine:
        if not c.account:
            raise ValueError("Snowflake connection requires an account identifier.")
        url = URL.create(
            "snowflake",
            username=c.username,
            password=pwd,
            host=c.account,
            database=c.database_name,
            query={
                k: v
                for k, v in {
                    "schema": c.schema_name,
                    "warehouse": c.warehouse,
                    "role": c.role,
                }.items()
                if v
            },
        )
        return create_engine(url, pool_pre_ping=True)

    def _db2(self, c: Connection, pwd: str) -> Engine:
        url = URL.create(
            "db2+ibm_db",
            username=c.username,
            password=pwd,
            host=c.host,
            port=self._port(c),
            database=c.database_name,
        )
        return create_engine(url, pool_pre_ping=True)

    def _teradata(self, c: Connection, pwd: str) -> Engine:
        url = URL.create(
            "teradatasql",
            username=c.username,
            password=pwd,
            host=c.host,
            query={
                k: v
                for k, v in {
                    "database": c.database_name,
                    "dbs_port": str(c.port) if c.port else None,
                }.items()
                if v
            },
        )
        return create_engine(url, pool_pre_ping=True)

    def _redshift(self, c: Connection, pwd: str) -> Engine:
        url = URL.create(
            "redshift+redshift_connector",
            username=c.username,
            password=pwd,
            host=c.host,
            port=self._port(c),
            database=c.database_name,
        )
        return create_engine(url, pool_pre_ping=True)

    def _databricks(self, c: Connection, pwd: str) -> Engine:
        """PAT auth: username fixed to 'token', password = personal access token."""
        if not c.http_path:
            raise ValueError("Databricks connection requires an HTTP Path.")
        url = URL.create(
            "databricks",
            username="token",
            password=pwd,
            host=c.host,
            port=self._port(c),
            query={
                k: v
                for k, v in {
                    "http_path": c.http_path,
                    "catalog": c.catalog,
                    "schema": c.schema_name,
                }.items()
                if v
            },
        )
        return create_engine(url, pool_pre_ping=True)

    def _hive(self, c: Connection, pwd: str) -> Engine:
        """HiveServer2 / Spark Thrift Server via PyHive."""
        connect_args = {}
        auth = c.options().get("auth") or ("LDAP" if pwd else None)
        if auth:
            connect_args["auth"] = auth
        url = URL.create(
            "hive",
            username=c.username,
            password=pwd or None,
            host=c.host,
            port=self._port(c),
            database=c.database_name or "default",
        )
        return create_engine(url, connect_args=connect_args, pool_pre_ping=True)

    def _sap_hana(self, c: Connection, pwd: str) -> Engine:
        url = URL.create(
            "hana+hdbcli",
            username=c.username,
            password=pwd,
            host=c.host,
            port=self._port(c),
            database=c.database_name,
        )
        return create_engine(url, pool_pre_ping=True)
