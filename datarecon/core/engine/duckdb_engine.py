"""
DataRecon AI — Community Edition
Shared DuckDB query helper (ADR-0001).

Every new validation module (Schema, Record Count, Duplicate, Nullability,
Aggregation, Profiling, File Comparison) registers its extracted Pandas
DataFrame(s) as DuckDB views through this helper and expresses its logic as
SQL. DuckDB's Pandas integration is zero-copy (Arrow-backed), so there is no
separate ingestion/serialization cost versus operating on the DataFrame
directly.

Module 6 (Full Data Validation) does NOT use this helper — see ADR-0001 for
why it keeps its existing, separately-tested Pandas `ComparisonEngine`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

import pandas as pd

try:
    import duckdb

    _DUCKDB_AVAILABLE = True
except ImportError:  # pragma: no cover - duckdb is a core dependency
    _DUCKDB_AVAILABLE = False

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DuckDBUnavailableError(RuntimeError):
    """Raised when the (core, non-optional) duckdb package is not installed."""


def quote_identifier(name: str) -> str:
    """Double-quote a SQL identifier (column/table name), escaping embedded quotes.

    Always quoting (rather than only when "needed") means callers never have
    to reason about which column names are safe to interpolate unquoted.
    """
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def duckdb_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    """Yield a fresh in-memory DuckDB connection, closed on exit."""
    if not _DUCKDB_AVAILABLE:
        raise DuckDBUnavailableError(
            "duckdb is a core Community Edition dependency but is not installed "
            "in this environment (pip install duckdb)."
        )
    con = duckdb.connect(database=":memory:")
    try:
        yield con
    finally:
        con.close()


@contextmanager
def registered_view(
    con: duckdb.DuckDBPyConnection, view_name: str, frame: pd.DataFrame
) -> Iterator[str]:
    """Register `frame` as a DuckDB view under a safe, quoted identifier.

    Yields the quoted view name to use in SQL. DuckDB's DataFrame
    replacement scan holds a reference to `frame`, so the view is valid for
    the lifetime of the connection/frame; explicit unregistration keeps
    connections reusable across multiple validations without leaking views.
    """
    if not _IDENTIFIER_RE.match(view_name):
        raise ValueError(f"Invalid DuckDB view name: {view_name!r}")
    con.register(view_name, frame)
    try:
        yield quote_identifier(view_name)
    finally:
        con.unregister(view_name)


def query_df(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    """Execute `sql` and return the result as a Pandas DataFrame."""
    return con.execute(sql).fetchdf()
