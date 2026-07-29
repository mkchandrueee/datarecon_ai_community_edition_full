"""Unit tests — shared DuckDB query helper (ADR-0001)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.core.engine.duckdb_engine import (
    duckdb_connection,
    query_df,
    quote_identifier,
    registered_view,
)


def test_quote_identifier_wraps_in_double_quotes() -> None:
    assert quote_identifier("CUST_ID") == '"CUST_ID"'


def test_quote_identifier_escapes_embedded_quotes() -> None:
    assert quote_identifier('weird"name') == '"weird""name"'


def test_registered_view_runs_sql_against_dataframe() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    with duckdb_connection() as con, registered_view(con, "t", df) as view:
        result = query_df(con, f"SELECT COUNT(*) AS n FROM {view}")
    assert result["n"].iloc[0] == 3


def test_registered_view_rejects_unsafe_names() -> None:
    df = pd.DataFrame({"a": [1]})
    with (
        duckdb_connection() as con,
        pytest.raises(ValueError, match="Invalid DuckDB view name"),
        registered_view(con, "not; safe", df),
    ):
        pass


def test_registered_view_unregisters_on_exit() -> None:
    df = pd.DataFrame({"a": [1]})
    with duckdb_connection() as con:
        with registered_view(con, "temp_view", df):
            pass
        with pytest.raises(Exception):  # noqa: B017 - duckdb raises its own CatalogException
            query_df(con, 'SELECT * FROM "temp_view"')


def test_two_views_can_be_joined() -> None:
    left = pd.DataFrame({"id": [1, 2, 3]})
    right = pd.DataFrame({"id": [2, 3, 4]})
    with (
        duckdb_connection() as con,
        registered_view(con, "l", left) as lv,
        registered_view(con, "r", right) as rv,
    ):
        result = query_df(
            con, f"SELECT {lv}.id FROM {lv} JOIN {rv} ON {lv}.id = {rv}.id ORDER BY 1"
        )
    assert result["id"].tolist() == [2, 3]
