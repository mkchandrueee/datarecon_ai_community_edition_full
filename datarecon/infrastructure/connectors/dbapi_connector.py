# datarecon/infrastructure/connectors/dbapi_connector.py  (NEW)
# Generic ODBC / JDBC connectivity (PRD Module 1: Generic Connectivity) plus
# sources without stable SQLAlchemy dialects: Informix and IDMS (mainframe;
# reached through the CA IDMS Server ODBC/JDBC bridge).
from __future__ import annotations

from typing import Any

from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import DatabaseType

_INFORMIX_ODBC_TEMPLATE = (
    "DRIVER={{{driver}}};HOST={host};SERVICE={port};DATABASE={database};"
    "SERVER={server};UID={uid};PWD={pwd};PROTOCOL=onsoctcp;"
)


class DBAPIConnectorFactory:
    """Builds raw DBAPI connections for ODBC (pyodbc) and JDBC (jaydebeapi)."""

    def create(self, conn: Connection, plaintext_password: str = "") -> Any:
        if conn.jdbc_url or conn.database_type == DatabaseType.JDBC:
            return self._jdbc(conn, plaintext_password)
        return self._odbc(conn, plaintext_password)

    def test(self, conn: Connection, plaintext_password: str = "") -> None:
        cxn = self.create(conn, plaintext_password)
        try:
            cur = cxn.cursor()
            cur.execute(self._test_query(conn))
            cur.fetchone()
            cur.close()
        finally:
            cxn.close()

    @staticmethod
    def _test_query(conn: Connection) -> str:
        if conn.database_type == DatabaseType.INFORMIX:
            return "SELECT FIRST 1 1 FROM systables"
        return "SELECT 1"

    # ---------- ODBC ----------
    def _odbc(self, c: Connection, pwd: str):
        import pyodbc

        conn_str = self._odbc_connection_string(c, pwd)
        return pyodbc.connect(conn_str, timeout=10)

    @staticmethod
    def _odbc_connection_string(c: Connection, pwd: str) -> str:
        opts = c.options()
        if opts.get("connection_string"):
            return opts["connection_string"].format(uid=c.username or "", pwd=pwd)
        if c.database_type == DatabaseType.INFORMIX:
            if not c.driver:
                raise ValueError("Informix requires an ODBC driver name or DSN.")
            return _INFORMIX_ODBC_TEMPLATE.format(
                driver=c.driver,
                host=c.host,
                port=c.port or 9088,
                database=c.database_name,
                server=opts.get("server", ""),
                uid=c.username or "",
                pwd=pwd,
            )
        if c.driver and "=" not in c.driver:
            # DSN-based (typical for ODBC generic and IDMS Server)
            parts = [f"DSN={c.driver}"]
        elif c.driver:
            parts = [f"DRIVER={{{c.driver}}}"]
            if c.host:
                parts.append(f"SERVER={c.host}")
            if c.port:
                parts.append(f"PORT={c.port}")
            if c.database_name:
                parts.append(f"DATABASE={c.database_name}")
        else:
            raise ValueError("ODBC connection requires a DSN or driver name.")
        if c.username:
            parts.append(f"UID={c.username}")
        if pwd:
            parts.append(f"PWD={pwd}")
        return ";".join(parts) + ";"

    # ---------- JDBC ----------
    @staticmethod
    def _jdbc(c: Connection, pwd: str):
        import jaydebeapi

        if not c.jdbc_url or not c.driver_class:
            raise ValueError("JDBC connection requires a JDBC URL and driver class.")
        jars: list | None = (
            [p.strip() for p in c.driver_location.split(",")] if c.driver_location else None
        )
        return jaydebeapi.connect(
            c.driver_class,
            c.jdbc_url,
            [c.username or "", pwd or ""],
            jars=jars,
        )
