# Architecture Decision Records

Per the Master PRD's instruction to record ADRs for ambiguous calls
instead of asking, these document the decisions made while building the
Community Edition against the PRD.

| ADR | Decision |
|---|---|
| [0001](0001-compare-engine-duckdb-polars-pandas.md) | DuckDB is the query engine for new modules; Module 6 keeps its existing, separately-tested Pandas engine rather than risking a rewrite; Polars accelerates file reads |
| [0002](0002-community-edition-module-scope.md) | Exactly the PRD 2.1 module list is implemented; everything else is Enterprise-only and out of scope for this codebase |
| [0003](0003-optional-connector-extras.md) | Heavyweight/niche database drivers are optional `pyproject.toml` extras, not core dependencies; also documents three dependency pins that were fixed after this codebase failed to install end-to-end |
| [0004](0004-run-history-summary-only-persistence.md) | Run history persists summary metrics only, not full row-level results, to keep the SQLite metadata store bounded |
| [0005](0005-projects-and-test-suites.md) | Projects group named, re-runnable Test Suites for regression checks; scheduling fields are reserved on the schema but not executed — no scheduler daemon is added in this iteration |
| [0006](0006-validation-run-project-attribution.md) | ValidationRun carries a project_id (the ADR-0005 Project, not the older Connection.project tag) so the Dashboard can filter by project; existing databases migrate in place |
| [0007](0007-schema-catalog-metadata-comparison.md) | Schema Validation adds native catalog metadata (length/key columns/defaults) as a second, additive comparison layer via SQLAlchemy's Inspector — only available for table-backed (not custom-query) relational connections |
| [0008](0008-run-detail-parquet-store.md) | Row-level run detail is persisted separately from the bounded SQLite metadata store, as per-run Parquet files in a new `RunDetailStore`, so Reports can replay a past run's mismatch/duplicate/profile rows |
| [0009](0009-case-insensitive-column-matching.md) | Column *names* are matched case-insensitively across every module (source spelling canonical), since databases fold identifiers differently and a CUSTOMER_ID/customer_id split otherwise broke Full Data Validation and double-counted Schema mismatches |
| [0010](0010-csv-export-for-every-payload-shape.md) | CSV export handles zero, one, or many data sections instead of raising — summary-only reports export their metrics and multi-section reports stack under banner lines, so every module has a working CSV download |
