# datarecon/domain/entities/foreign_key_metadata.py
# One declared foreign-key constraint on a table, read from the database's
# catalog via SQLAlchemy's Inspector (same availability rules as
# ColumnCatalogMetadata — see ADR-0007).
#
# Used by Referential Integrity (ADR-0012) to offer the relationships the
# database already knows about, so the common case needs no typing.
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ForeignKeyMetadata:
    """A child->parent relationship as the catalog declares it.

    `columns` and `referred_columns` are positionally paired: the i-th child
    column references the i-th parent column, which is how composite keys work.
    """

    name: str | None
    columns: list[str] = field(default_factory=list)
    referred_table: str = ""
    referred_schema: str | None = None
    referred_columns: list[str] = field(default_factory=list)

    @property
    def qualified_parent(self) -> str:
        """Parent table as the user would type it, schema-qualified if needed."""
        return f"{self.referred_schema}.{self.referred_table}" if self.referred_schema else self.referred_table

    def label(self, child_table: str) -> str:
        """Human-readable summary for a picker."""
        child_cols = ", ".join(self.columns)
        parent_cols = ", ".join(self.referred_columns)
        return f"{child_table}({child_cols}) -> {self.qualified_parent}({parent_cols})"
