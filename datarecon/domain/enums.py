# datarecon/domain/enums.py  (MODIFIED — full PRD Module 1 source matrix)
from __future__ import annotations

from enum import StrEnum


class ConnectionCategory(StrEnum):
    RELATIONAL = "Relational Database"
    NOSQL = "NoSQL Database"
    STORAGE = "Cloud Storage"
    FILE = "File Source"
    GENERIC = "Generic Connectivity"


class DatabaseType(StrEnum):
    # Relational / analytical
    ORACLE = "Oracle"
    SQLSERVER = "SQL Server"
    DB2 = "DB2"
    INFORMIX = "Informix"
    POSTGRESQL = "PostgreSQL"
    MYSQL = "MySQL"
    MARIADB = "MariaDB"
    SNOWFLAKE = "Snowflake"
    SYNAPSE = "Synapse"
    AZURE_SQL = "Azure SQL"
    TERADATA = "Teradata"
    IDMS = "IDMS"
    REDSHIFT = "Redshift"
    DATABRICKS = "Databricks"
    HIVE = "Hive"
    SPARK = "Spark"
    GREENPLUM = "Greenplum"
    SAP_HANA = "SAP HANA"
    SQLITE = "SQLite"
    # NoSQL
    MONGODB = "MongoDB"
    # Cloud storage
    AWS_S3 = "AWS S3"
    AZURE_BLOB = "Azure Blob Storage"
    AZURE_DATA_LAKE = "Azure Data Lake"
    GCS = "Google Cloud Storage"
    # File sources
    EXCEL = "Excel"
    CSV = "CSV"
    XML = "XML"
    JSON = "JSON"
    PARQUET = "Parquet"
    AVRO = "Avro"
    # Generic connectivity
    JDBC = "JDBC"
    ODBC = "ODBC"


_CATEGORY: dict[DatabaseType, ConnectionCategory] = {
    **dict.fromkeys(
        (
            DatabaseType.ORACLE,
            DatabaseType.SQLSERVER,
            DatabaseType.DB2,
            DatabaseType.INFORMIX,
            DatabaseType.POSTGRESQL,
            DatabaseType.MYSQL,
            DatabaseType.MARIADB,
            DatabaseType.SNOWFLAKE,
            DatabaseType.SYNAPSE,
            DatabaseType.AZURE_SQL,
            DatabaseType.TERADATA,
            DatabaseType.IDMS,
            DatabaseType.REDSHIFT,
            DatabaseType.DATABRICKS,
            DatabaseType.HIVE,
            DatabaseType.SPARK,
            DatabaseType.GREENPLUM,
            DatabaseType.SAP_HANA,
            DatabaseType.SQLITE,
        ),
        ConnectionCategory.RELATIONAL,
    ),
    DatabaseType.MONGODB: ConnectionCategory.NOSQL,
    **dict.fromkeys(
        (
            DatabaseType.AWS_S3,
            DatabaseType.AZURE_BLOB,
            DatabaseType.AZURE_DATA_LAKE,
            DatabaseType.GCS,
        ),
        ConnectionCategory.STORAGE,
    ),
    **dict.fromkeys(
        (
            DatabaseType.EXCEL,
            DatabaseType.CSV,
            DatabaseType.XML,
            DatabaseType.JSON,
            DatabaseType.PARQUET,
            DatabaseType.AVRO,
        ),
        ConnectionCategory.FILE,
    ),
    DatabaseType.JDBC: ConnectionCategory.GENERIC,
    DatabaseType.ODBC: ConnectionCategory.GENERIC,
}


def category_of(db_type: DatabaseType) -> ConnectionCategory:
    return _CATEGORY[db_type]


class FileFormat(StrEnum):
    CSV = "csv"
    EXCEL = "excel"
    XML = "xml"
    JSON = "json"
    PARQUET = "parquet"
    AVRO = "avro"


_FILE_TYPE_FORMAT: dict[DatabaseType, FileFormat] = {
    DatabaseType.CSV: FileFormat.CSV,
    DatabaseType.EXCEL: FileFormat.EXCEL,
    DatabaseType.XML: FileFormat.XML,
    DatabaseType.JSON: FileFormat.JSON,
    DatabaseType.PARQUET: FileFormat.PARQUET,
    DatabaseType.AVRO: FileFormat.AVRO,
}

_EXTENSION_FORMAT: dict[str, FileFormat] = {
    ".csv": FileFormat.CSV,
    ".txt": FileFormat.CSV,
    ".xlsx": FileFormat.EXCEL,
    ".xls": FileFormat.EXCEL,
    ".xlsm": FileFormat.EXCEL,
    ".xml": FileFormat.XML,
    ".json": FileFormat.JSON,
    ".jsonl": FileFormat.JSON,
    ".ndjson": FileFormat.JSON,
    ".parquet": FileFormat.PARQUET,
    ".pq": FileFormat.PARQUET,
    ".avro": FileFormat.AVRO,
}


def file_format_for(db_type: DatabaseType) -> FileFormat | None:
    return _FILE_TYPE_FORMAT.get(db_type)


def file_format_from_path(path: str) -> FileFormat | None:
    from pathlib import PurePath

    return _EXTENSION_FORMAT.get(PurePath(path).suffix.lower())


class ConnectionRole(StrEnum):
    SOURCE = "Source"
    TARGET = "Target"


class Environment(StrEnum):
    DEV = "DEV"
    QA = "QA"
    UAT = "UAT"
    PROD = "PROD"


class ValidationModule(StrEnum):
    """PRD Community Edition module list (ADR-0002)."""

    SCHEMA = "Schema Validation"
    RECORD_COUNT = "Record Count Validation"
    DUPLICATE = "Duplicate Validation"
    NULLABILITY = "Nullability Validation"
    AGGREGATION = "Aggregation Validation"
    FULL_DATA = "Full Data Validation"
    REFERENTIAL_INTEGRITY = "Referential Integrity"
    PROFILING = "Data Profiling"
    FILE_COMPARISON = "File Comparison"

    @property
    def code(self) -> str:
        """Short prefix stamped onto Test Suite names (RC_CUSTOMER_MASTER),
        so a suite's module is readable at a glance in lists and reports."""
        return _MODULE_CODES[self]


_MODULE_CODES = {
    ValidationModule.SCHEMA: "SC",
    ValidationModule.RECORD_COUNT: "RC",
    ValidationModule.DUPLICATE: "DV",
    ValidationModule.NULLABILITY: "NV",
    ValidationModule.AGGREGATION: "AG",
    ValidationModule.FULL_DATA: "FD",
    ValidationModule.REFERENTIAL_INTEGRITY: "RI",
    ValidationModule.PROFILING: "DP",
    ValidationModule.FILE_COMPARISON: "FC",
}


class RunStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class AggregateFunction(StrEnum):
    """PRD Module 7: COUNT, SUM, AVG, MIN, MAX, COUNT(DISTINCT)."""

    COUNT = "COUNT"
    COUNT_DISTINCT = "COUNT_DISTINCT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"


class ReportFormat(StrEnum):
    """PRD Module 18 (Community scope): Excel, CSV, PDF, JSON."""

    EXCEL = "excel"
    CSV = "csv"
    PDF = "pdf"
    JSON = "json"
