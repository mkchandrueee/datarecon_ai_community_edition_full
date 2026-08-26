# ADR-0008: Row-level run detail is persisted separately, as per-run Parquet files

## Status
Accepted

## Context
ADR-0004 deliberately kept the SQLite metadata store bounded by persisting
only summary metrics for every `ValidationRun`; row-level results (mismatch
rows, duplicate samples, null detail, profiling top-values, schema diffs)
lived only in `st.session_state` for the browser session and were an
explicit, recorded scope cut — Module 18's Reports page could show a past
run's numbers but never its rows, and re-opening yesterday's run meant
re-running it to get the mismatch file back.

That gap is now being closed for Community Edition without reopening
ADR-0004's core bounded-SQLite decision: the fix is a second store, not a
bigger `validation_runs` table.

## Decision
- `RunDetailStore` (`infrastructure/persistence/run_detail_store.py`) is a
  new, independent persistence component. It writes each named "section"
  DataFrame a module produces to its own Parquet file under
  `data/run_details/<run_id>/<section>.parquet`, plus a small JSON
  manifest (`_manifest.json`) mapping each file's slugified name back to
  its original display title (titles can contain characters that don't
  round-trip cleanly through a filename, e.g. `Top Values - a/b`).
  Parquet, not SQLite, because these payloads are exactly the shape
  Parquet is built for — columnar, DataFrame-native (via `pyarrow`,
  already a core dependency for the DuckDB/Polars engine per ADR-0001) —
  and keeping them out of the `.db` file means the metadata store's size
  stays predictable regardless of how much detail accumulates.
- Every module service that produces a result DataFrame — Schema, Record
  Count, Duplicate, Nullability, Aggregation, Full Data Validation, Data
  Profiling — takes a `detail_store: RunDetailStore` constructor
  dependency (composed once in `app.py`, alongside the existing
  `run_repository`) and calls `detail_store.save(run.run_id, {...})` on
  the success path of `execute()`, immediately after `record_run()`. File
  Comparison is excluded — its checksum-only result has no DataFrame to
  persist. A service only saves a section when it's non-empty, mirroring
  the same "nothing to show" checks each module's own view already made
  before adding a `ReportSection` (e.g. Record Count's group breakdown is
  only produced when `group_by` is set; an empty result is not written).
- This is additive, not a replacement: `record_run()` and the
  `validation_runs` table are unchanged, so ADR-0004's bound on SQLite
  growth still holds. `RunDetailStore` has no retention/eviction policy of
  its own in this iteration — the same "single-node tool, not a warehouse"
  posture as the rest of Community Edition; disk usage is the operator's
  concern, not a background job's.
- Module 18's Reports page now reads back a selected run's sections via
  `detail_store.load_all(run.run_id)` and renders each in its own tab,
  reusing the same red/green highlighting Full Data Validation's own view
  uses. That highlighting was pulled out of `full_data_view.py` into
  `presentation/components/mismatch_styling.py` specifically so Reports
  could reuse it without importing view code or duplicating the Styler
  logic. Runs recorded before this ADR (or by File Comparison) simply have
  no manifest on disk; Reports shows a caption instead of erroring.

## Consequences
- Community Edition gains "re-download yesterday's mismatch file" without
  the SQLite metadata store growing per-row — the two stores can be
  reasoned about, backed up, or pruned independently.
- Every module service constructor now requires a `RunDetailStore`; this
  is a breaking change to direct instantiation (composition root, saved
  Test Suite re-runs, and every existing unit test's service fixture),
  accepted as a one-time mechanical update rather than making the
  parameter optional and risking call sites silently getting no detail
  persistence.
- Parquet section files accumulate on disk with no automatic cleanup; an
  operator who runs a very large number of validations over a long period
  is expected to prune `data/run_details/` manually (e.g. by run age),
  same as they would for the SQLite file growing. Automated retention
  policies remain an Enterprise Module 34 concern (tiered
  hot/cold storage), consistent with ADR-0004.
