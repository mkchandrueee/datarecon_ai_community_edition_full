# datarecon/domain/entities/column_catalog_metadata.py
# Native DB catalog metadata for one column of a table-backed relational
# connection (length/PK/default) — the attributes ADR-0001 explicitly
# scoped OUT of Module 2 in favor of DataFrame-inferred dtype comparison.
# See ADR-0007: these are only available when a table name (not an
# arbitrary SQL query) is given for a connection SQLAlchemy can inspect.
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnCatalogMetadata:
    name: str
    native_type: str
    max_length: int | None
    nullable: bool
    default: str | None
    is_primary_key: bool
