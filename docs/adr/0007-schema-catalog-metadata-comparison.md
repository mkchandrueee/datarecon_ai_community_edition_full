# ADR-0007: Schema Validation adds native catalog metadata (length/key/default) as a second, additive comparison layer

## Status
Accepted

## Context
ADR-0001 explicitly scoped Module 2 (Schema Validation) to compare
DataFrame-inferred structure — column name, position, and a normalized
type category — rather than native database catalog metadata
(precision/scale/PK/FK/indexes/collation), because a small extracted
sample carries dtypes but not DDL-level constraints. The user later asked
for exactly that cut scope: column length, key columns, and default
values. Column length and defaults categorically cannot be derived from
sampled row data (a `VARCHAR(50)` column holding only 3-character values
gives no signal of its declared length; a default value only shows up
for rows that used it, if any were sampled), so satisfying this request
requires reading actual catalog metadata, not more row sampling.

## Decision
- `DataExtractor.get_catalog_columns(conn, table, secret)` (infrastructure
  layer) uses SQLAlchemy's `Inspector` (`inspect(engine).get_columns()` /
  `.get_pk_constraint()`) to read a physical table's column type (with
  length/precision when the dialect exposes it), nullability, default
  expression, and primary-key membership. `DataExtractionService.get_table_
  catalog_metadata()` wraps it with connection lookup + credential
  decryption, mirroring the existing `extract_dataframe()` pattern.
- This only works — and is only attempted — when: (a) the connection is
  `RELATIONAL` and `EngineFactory` supports its database type (i.e. it's
  SQLAlchemy-backed), and (b) the request names a physical **table**, not
  a custom SQL query (a query's result set has no single catalog entry to
  inspect). Any other case, or any exception during inspection (permission
  denied, table not found, etc.), returns `None` — a soft "not available"
  signal, never a hard failure of the validation run.
- `SchemaValidationService._compare_schemas()` keeps its existing
  name/type/position comparison (`status` column: MATCH/TYPE_MISMATCH/
  MISSING_IN_TARGET/EXTRA_IN_TARGET/POSITION_MISMATCH) completely
  unchanged, and layers three new *independent* columns on top —
  `length_match`, `key_match`, `default_match` — each `True`/`False` only
  when catalog metadata was available for that column on **both** sides,
  else `None` ("not evaluated"). A mismatch on any of the three counts
  toward a new `attribute_mismatches` summary metric and fails the overall
  run, exactly like a name/type mismatch does.
- Default-value comparison is a raw string comparison of whatever the
  DB dialect reports (e.g. SQLite reports the literal DDL expression,
  quotes included). This is intentionally simple: comparing *semantically
  equivalent* defaults across two different DB dialects (e.g. `now()` vs
  `CURRENT_TIMESTAMP`) is out of scope — flagging a textual difference and
  letting the user judge it is preferable to guessing at cross-dialect
  equivalence rules.

## Consequences
- Community Edition still never requires SQL-parsing a user's custom
  query to guess at catalog metadata — the existing "point at a table"
  vs. "write custom SQL" choice in the UI now also determines whether the
  richer comparison runs, which is a natural, honest boundary rather than
  a hidden limitation.
- The DataFrame-based comparison remains the only thing Schema Validation
  can rely on for File sources, NoSQL, cloud storage, and any relational
  type `EngineFactory` doesn't wrap in SQLAlchemy — catalog enrichment is
  additive, not a replacement, so those connections keep working exactly
  as before (just without the three extra columns, shown as blank/`None`
  in the UI with an explanatory caption).
