"""Unit tests — SqlGenerationService (metadata-driven SQL, ADR-0011)."""

from __future__ import annotations

import pytest

from datarecon.application.services.sql_generation_service import (
    SqlGenerationService,
    TableGeneration,
)
from datarecon.domain.entities.column_catalog_metadata import ColumnCatalogMetadata
from datarecon.domain.enums import DatabaseType, ValidationModule


class FakeExtraction:
    """Stands in for DataExtractionService's catalog lookup."""

    def __init__(self, catalogs, database_type=DatabaseType.POSTGRESQL, raises=None):
        self._catalogs = catalogs
        self._database_type = database_type
        self._raises = raises

    def get_table_catalog_metadata(self, connection_id, table):
        if self._raises:
            raise self._raises
        return self._catalogs.get(table)

    def get_database_type(self, connection_id):
        return self._database_type


def _columns():
    return [
        ColumnCatalogMetadata("CUSTOMER_ID", "INTEGER", None, False, None, True),
        ColumnCatalogMetadata("EMAIL_ID", "VARCHAR(200)", 200, False, None, False),
        ColumnCatalogMetadata("NICKNAME", "VARCHAR(50)", 50, True, None, False),
    ]


@pytest.fixture
def service() -> SqlGenerationService:
    return SqlGenerationService(FakeExtraction({"CUSTOMER_MASTER": _columns()}))


def _sql_for(result: TableGeneration, module: ValidationModule) -> str:
    return next(s.sql for s in result.statements if s.module == module)


def test_generates_one_statement_per_supported_module(service) -> None:
    result = service.generate("c1", "CUSTOMER_MASTER")
    assert result.ok
    assert {s.module for s in result.statements} == {
        ValidationModule.SCHEMA,
        ValidationModule.RECORD_COUNT,
        ValidationModule.DUPLICATE,
        ValidationModule.NULLABILITY,
    }


def test_sql_lists_every_catalog_column(service) -> None:
    sql = _sql_for(service.generate("c1", "CUSTOMER_MASTER"), ValidationModule.SCHEMA)
    for column in ("CUSTOMER_ID", "EMAIL_ID", "NICKNAME"):
        assert column in sql
    assert "FROM CUSTOMER_MASTER" in sql


def test_record_count_sql_is_row_returning_not_aggregated(service) -> None:
    """Record Count counts extracted rows, so COUNT(*) would report 1."""
    sql = _sql_for(service.generate("c1", "CUSTOMER_MASTER"), ValidationModule.RECORD_COUNT)
    assert "COUNT(" not in sql.upper()
    assert sql.upper().startswith("SELECT")


def test_duplicate_suggests_the_primary_key(service) -> None:
    statement = next(
        s
        for s in service.generate("c1", "CUSTOMER_MASTER").statements
        if s.module == ValidationModule.DUPLICATE
    )
    assert statement.suggested_keys == ["CUSTOMER_ID"]


def test_nullability_suggests_not_null_columns(service) -> None:
    statement = next(
        s
        for s in service.generate("c1", "CUSTOMER_MASTER").statements
        if s.module == ValidationModule.NULLABILITY
    )
    assert statement.suggested_columns == ["CUSTOMER_ID", "EMAIL_ID"]
    assert "NICKNAME" not in statement.suggested_columns


def test_can_restrict_to_selected_modules(service) -> None:
    result = service.generate("c1", "CUSTOMER_MASTER", modules=(ValidationModule.SCHEMA,))
    assert [s.module for s in result.statements] == [ValidationModule.SCHEMA]


def test_unknown_table_reports_an_error_rather_than_raising(service) -> None:
    result = service.generate("c1", "NO_SUCH_TABLE")
    assert not result.ok
    assert "NO_SUCH_TABLE" in result.error


def test_blank_table_name_is_rejected(service) -> None:
    assert not service.generate("c1", "   ").ok


def test_connector_failure_is_reported_per_table() -> None:
    service = SqlGenerationService(FakeExtraction({}, raises=RuntimeError("driver exploded")))
    result = service.generate("c1", "ANY")
    assert not result.ok
    assert "driver exploded" in result.error


# ---------- identifier quoting ----------


def test_plain_identifiers_are_left_unquoted(service) -> None:
    sql = _sql_for(service.generate("c1", "CUSTOMER_MASTER"), ValidationModule.SCHEMA)
    assert '"CUSTOMER_ID"' not in sql
    assert "CUSTOMER_ID" in sql


def test_awkward_identifiers_are_quoted_for_the_dialect() -> None:
    columns = [ColumnCatalogMetadata("Order Date", "DATE", None, True, None, False)]
    service = SqlGenerationService(FakeExtraction({"T": columns}, DatabaseType.POSTGRESQL))
    assert '"Order Date"' in _sql_for(service.generate("c1", "T"), ValidationModule.SCHEMA)


def test_mysql_uses_backticks() -> None:
    columns = [ColumnCatalogMetadata("Order Date", "DATE", None, True, None, False)]
    service = SqlGenerationService(FakeExtraction({"T": columns}, DatabaseType.MYSQL))
    assert "`Order Date`" in _sql_for(service.generate("c1", "T"), ValidationModule.SCHEMA)


def test_sqlserver_uses_brackets() -> None:
    columns = [ColumnCatalogMetadata("Order Date", "DATE", None, True, None, False)]
    service = SqlGenerationService(FakeExtraction({"T": columns}, DatabaseType.SQLSERVER))
    assert "[Order Date]" in _sql_for(service.generate("c1", "T"), ValidationModule.SCHEMA)


# ---------- bulk generation ----------


def test_bulk_generates_for_every_table() -> None:
    catalogs = {"A": _columns(), "B": _columns()}
    service = SqlGenerationService(FakeExtraction(catalogs))
    results = service.generate_bulk("c1", ["A", "B"])
    assert [r.table for r in results] == ["A", "B"]
    assert all(r.ok for r in results)


def test_bulk_continues_past_a_failing_table() -> None:
    service = SqlGenerationService(FakeExtraction({"A": _columns()}))
    results = service.generate_bulk("c1", ["A", "MISSING", "A"])
    by_table = {r.table: r for r in results}
    assert by_table["A"].ok
    assert not by_table["MISSING"].ok


def test_bulk_deduplicates_case_insensitively() -> None:
    service = SqlGenerationService(FakeExtraction({"A": _columns()}))
    assert [r.table for r in service.generate_bulk("c1", ["A", "a", " A "])] == ["A"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("A, B, C", ["A", "B", "C"]),
        ("A\nB\nC", ["A", "B", "C"]),
        ("A; B", ["A", "B"]),
        ("  A , , B  ", ["A", "B"]),
        ("", []),
    ],
)
def test_parse_table_list_accepts_common_separators(raw, expected) -> None:
    assert SqlGenerationService.parse_table_list(raw) == expected
