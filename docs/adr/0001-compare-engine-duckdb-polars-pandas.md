# ADR-0001: DuckDB as the query engine for new modules; Module 6 keeps its proven Pandas engine; Polars for fast reads

## Status
Accepted

## Context
PRD section 2.1 mandates the Community Edition compare engine be
"DuckDB + Polars compare engine (Pandas fallback)", targeting up to ~10M
records on a single node. The codebase already had a working, fully
vectorized Pandas `ComparisonEngine` (Module 6: key-based row diff with
configurable null/tolerance/case semantics and a chunked cell-level
mismatch diff), backed by 21 passing tests that encode subtle, deliberate
behavior (e.g. boundary-safe float tolerance, NULL==NULL semantics,
duplicate-key handling). Reimplementing that exact behavior in DuckDB SQL
purely to satisfy the letter of "DuckDB primary" would risk silently
regressing tested semantics for marginal benefit at Community Edition's
stated scale (10M rows fits comfortably in memory for a vectorized Pandas
merge).

## Decision
- **Module 6 (Full Data Validation)** keeps its existing Pandas
  `ComparisonEngine` unchanged. It is already vectorized, already
  performant at the Community Edition ceiling, and its test suite is the
  spec for null/tolerance/duplicate-key behavior — there is no Pandas
  "fallback" to design here because there is no separate primary path to
  fall back from.
- **Every new module whose logic is row/aggregate-shaped** (Record Count,
  Duplicate, Nullability, Aggregation, Profiling) is built directly on
  **DuckDB SQL**, via a shared `datarecon.core.engine.duckdb_engine`
  helper that registers a Pandas DataFrame as a DuckDB view (zero-copy,
  no separate ingestion step) and runs SQL against it (`COUNT`,
  `GROUP BY`, `HAVING`, window functions for duplicate detection). These
  have no pre-existing implementation to regress against, so DuckDB is a
  low-risk, high-leverage fit for them.
- **Schema Validation** compares column *metadata* (names/dtypes), not
  row data, so it is plain Python/Pandas `dtypes` comparison — routing it
  through a SQL engine would add indirection without benefit. **File
  Comparison** delegates structure/count/full-data modes to the Schema,
  Record Count, and Full Data Validation services respectively (a file
  connection is just another `Connection` category — see Module 1), and
  adds its own whole-file checksum mode.
- **Polars** is used in the extraction/read path
  (`infrastructure/extraction/file_readers.py`) for large columnar file
  formats (Parquet, CSV) where its lazy, multi-threaded reader
  materially outperforms `pandas.read_csv`/`read_parquet`. Extraction
  still returns a Pandas DataFrame at the service boundary so every
  downstream module (old and new) keeps one DataFrame contract.
- If `duckdb` is not installed, the new modules' DuckDB helper raises a
  clear `RuntimeError` naming the missing dependency rather than silently
  degrading — DuckDB is a core dependency (see `pyproject.toml`), not
  optional, so this is a fail-fast install-time signal, not a runtime
  fallback path.

## Consequences
- Every new validation module has exactly one implementation
  (DuckDB SQL against a registered DataFrame), not three parallel
  Pandas/Polars/DuckDB code paths — this keeps the module count (7 new
  modules) tractable to build and test correctly.
- Module 6 is unchanged and keeps its 21 existing tests as the
  regression baseline.
- Community Edition's 10M-row ceiling means we do not need DuckDB's
  spill-to-disk tuning, out-of-core joins, or Arrow Flight; that
  complexity belongs to the Enterprise Edition's Module 32 (High-Volume
  Execution Engine), which is explicitly out of scope here (ADR-0002).
