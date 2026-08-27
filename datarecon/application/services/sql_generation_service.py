# datarecon/application/services/sql_generation_service.py
# Generates the custom SQL each validation module needs, from the table's real
# catalog metadata (see ADR-0011).
#
# The generation is metadata-driven rather than model-driven: the column list,
# primary key and nullability all come from the database's own catalog via
# SQLAlchemy's Inspector, so the SQL can only ever reference columns that
# actually exist. That matters more than it might sound — the modules consume
# their SQL in ways that are easy to get subtly wrong:
#
#   Record Count counts the *rows of the extracted frame*, so `SELECT COUNT(*)`
#   would return a single row and report a count of 1. Every generated query is
#   therefore row-returning, never pre-aggregated.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from datarecon.application.services.data_extraction_service import DataExtractionService
from datarecon.domain.entities.column_catalog_metadata import ColumnCatalogMetadata
from datarecon.domain.enums import DatabaseType, ValidationModule

#: Modules this service can write SQL for.
SUPPORTED_MODULES = (
    ValidationModule.SCHEMA,
    ValidationModule.RECORD_COUNT,
    ValidationModule.DUPLICATE,
    ValidationModule.NULLABILITY,
)

#: Dialects that don't use the SQL-standard double quote for identifiers.
_QUOTE_CHARS: dict[DatabaseType, tuple[str, str]] = {
    DatabaseType.MYSQL: ("`", "`"),
    DatabaseType.MARIADB: ("`", "`"),
    DatabaseType.SQLSERVER: ("[", "]"),
    DatabaseType.AZURE_SQL: ("[", "]"),
    DatabaseType.SYNAPSE: ("[", "]"),
    DatabaseType.HIVE: ("`", "`"),
    DatabaseType.SPARK: ("`", "`"),
    DatabaseType.DATABRICKS: ("`", "`"),
}

_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SqlGenerationError(ValueError):
    """Raised when SQL cannot be generated for a table."""


@dataclass(frozen=True)
class GeneratedSQL:
    """One module's SQL for one table, plus what the generator inferred."""

    module: ValidationModule
    table: str
    sql: str
    note: str
    #: Columns worth using as the duplicate/business key — the primary key when
    #: the catalog declares one. Empty when nothing could be inferred.
    suggested_keys: list[str] = field(default_factory=list)
    #: Columns worth null-checking — those the catalog marks NOT NULL, since a
    #: null there is a real defect rather than a permitted absence.
    suggested_columns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TableGeneration:
    """Everything generated for one table, or why nothing could be."""

    table: str
    statements: list[GeneratedSQL] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class SqlGenerationService:
    def __init__(self, extraction: DataExtractionService):
        self._extraction = extraction

    def generate(
        self,
        connection_id: str,
        table: str,
        modules: tuple[ValidationModule, ...] = SUPPORTED_MODULES,
    ) -> TableGeneration:
        """Generate SQL for one table. Never raises for a bad table name — the
        failure is returned on the result so a bulk run can continue."""
        table = table.strip()
        if not table:
            return TableGeneration(table=table, error="Table name is required.")

        try:
            columns = self._extraction.get_table_catalog_metadata(connection_id, table)
        except Exception as exc:  # connector/driver failures are per-table news
            return TableGeneration(table=table, error=str(exc))

        if not columns:
            return TableGeneration(
                table=table,
                error=(
                    f"No catalog metadata for '{table}'. Check the table exists and that "
                    "this connection type supports introspection."
                ),
            )

        quote = self._quoter(connection_id)
        return TableGeneration(
            table=table,
            statements=[
                self._for_module(module, table, columns, quote)
                for module in modules
                if module in SUPPORTED_MODULES
            ],
        )

    def generate_bulk(
        self,
        connection_id: str,
        tables: list[str],
        modules: tuple[ValidationModule, ...] = SUPPORTED_MODULES,
    ) -> list[TableGeneration]:
        """Generate for many tables in one pass. A table that fails is reported
        on its own result rather than aborting the batch."""
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in tables:
            name = raw.strip()
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                ordered.append(name)
        return [self.generate(connection_id, table, modules) for table in ordered]

    @staticmethod
    def parse_table_list(raw: str) -> list[str]:
        """Split a pasted table list on commas, newlines or semicolons."""
        return [part.strip() for part in re.split(r"[,\n;]+", raw) if part.strip()]

    # ------------------------------------------------------------------ #
    def _for_module(
        self,
        module: ValidationModule,
        table: str,
        columns: list[ColumnCatalogMetadata],
        quote: _Quoter,
    ) -> GeneratedSQL:
        names = [c.name for c in columns]
        select_list = ",\n       ".join(quote(n) for n in names)
        base = f"SELECT {select_list}\n  FROM {quote(table)}"
        keys = [c.name for c in columns if c.is_primary_key]
        not_null = [c.name for c in columns if not c.nullable]

        if module == ValidationModule.SCHEMA:
            note = (
                f"{len(names)} column(s). Schema Validation samples rows to infer types, "
                "so the query returns rows rather than metadata."
            )
            return GeneratedSQL(module, table, base, note)

        if module == ValidationModule.RECORD_COUNT:
            note = (
                "Returns rows, not COUNT(*) — Record Count counts the rows it "
                "extracts, so a pre-aggregated query would report a count of 1."
            )
            return GeneratedSQL(module, table, base, note)

        if module == ValidationModule.DUPLICATE:
            note = (
                f"Primary key {keys} pre-filled as the duplicate key."
                if keys
                else "No primary key in the catalog — choose the key column(s) manually."
            )
            return GeneratedSQL(module, table, base, note, suggested_keys=keys)

        note = (
            f"{len(not_null)} NOT NULL column(s) pre-filled — a null there is a defect."
            if not_null
            else "No NOT NULL columns declared; every column is checked by default."
        )
        return GeneratedSQL(module, table, base, note, suggested_columns=not_null)

    def _quoter(self, connection_id: str) -> _Quoter:
        database_type = self._extraction.get_database_type(connection_id)
        return _Quoter(*_QUOTE_CHARS.get(database_type, ('"', '"')))


@dataclass(frozen=True)
class _Quoter:
    """Quotes identifiers only when they need it.

    Leaving a plain name unquoted keeps the generated SQL readable and lets the
    database apply its own case folding — which is what an unquoted name in the
    user's own DDL would have done anyway.
    """

    open_char: str
    close_char: str

    def __call__(self, identifier: str) -> str:
        if _BARE_IDENTIFIER.match(identifier):
            return identifier
        escaped = identifier.replace(self.close_char, self.close_char * 2)
        return f"{self.open_char}{escaped}{self.close_char}"
