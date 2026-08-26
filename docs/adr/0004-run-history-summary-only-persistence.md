# ADR-0004: Run history persists summaries only, not row-level detail

## Status
Accepted

## Context
PRD Module 34 (Enterprise) describes tiered retention: "hot" results in
PostgreSQL, "cold" row-level results in object storage/Parquet. Community
Edition has neither a warehouse-grade metadata store nor object storage —
only SQLite. Modules 18 (Reporting) and 19 (Dashboard) both need run
history, but persisting full mismatch/duplicate/profile row sets to SQLite
for every run would grow the metadata DB unboundedly and is unnecessary
for a single-node tool where the person who ran the validation is looking
at the result in the same session.

## Decision
- `ValidationRun` (see `domain/entities/validation_run.py`) is the only
  thing written to the `validation_runs` table: module, name, status,
  a small JSON `summary` dict (counts/percentages/pass-fail — the numbers
  Module 19's dashboard widgets and trend charts need), connection ids,
  timing, and an error message on failure.
- Full result DataFrames (mismatch rows, duplicate samples, null detail,
  profiling histograms, schema diffs) are kept only in
  `st.session_state` for the duration of the browser session and are what
  Module 18's export buttons (Excel/CSV/PDF/JSON) serialize directly —
  they are never round-tripped through SQLite.
- Every module's application service returns a `(result, ValidationRun)`
  pair: the rich in-memory result for the view to render/export, and the
  lightweight run record for the repository to persist.

## Consequences
- The dashboard (Module 19) and trend analytics can show pass/fail
  history and metrics indefinitely without unbounded DB growth.
- Re-opening a past run from history shows its summary metrics but not
  its row-level detail — there is no "re-download yesterday's mismatch
  file" capability in Community Edition. This is an explicit, recorded
  scope cut, not an oversight; Enterprise Module 34's object-storage tier
  is the intended home for that capability.

**Update (ADR-0008):** the "no row-level detail" cut above was
specifically about the *SQLite metadata store* staying summary-only, not
about detail being unrecoverable altogether. ADR-0008 adds a separate,
Parquet-backed `RunDetailStore` alongside (not instead of) this table, so
Reports can now replay a past run's rows without the `validation_runs`
table itself growing unbounded — the decision above still holds exactly
as written for `record_run()`/`validation_runs`.
