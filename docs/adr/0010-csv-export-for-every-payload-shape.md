# ADR-0010: CSV export works for every payload shape

## Status
Accepted — amends ADR-0008's export surface.

## Context
`ReportingService._to_csv()` required a payload to hold exactly one data
section and raised `ReportingError` otherwise. That single rule produced
three distinct user-facing failures:

- Modules whose result is a summary and no table (Record Count, File
  Comparison) showed a dead **"CSV n/a"** caption where every other
  format offered a download.
- Full Data Validation, whose payload carries three sections, raised
  `ReportingError: CSV export requires exactly one data section, got 3`
  as an uncaught Streamlit traceback.
- Reports raised the same error with `got 0` when inspecting a run whose
  row-level detail had not been retained.

The guard was defensible in the abstract — CSV is one flat table and a
multi-section report has no single obvious shape — but "no correct CSV
exists" is a much stronger claim than the situation warranted, and the
component-level `try/except` that hid the first case only made the
feature look half-built.

## Decision
`_to_csv()` handles every shape and never raises:

- **One section** — unchanged: that table, as CSV.
- **No sections** — the summary metrics as a `metric,value` table. A run
  that measured something always has something to export.
- **Several sections** — the summary followed by each section, separated
  by `# <section title>` banner lines. Spreadsheet tools import this
  directly, and the banners keep it readable as plain text.
- `render_csv_download_button()` no longer suppresses empty frames: a
  header-only CSV states a real result ("no mismatches"), so the button
  stays live rather than vanishing when the news is good.

Excel and CSV now share `_summary_frame()`, so the summary sheet and the
summary block cannot drift apart.

## Consequences
- Every module offers a working CSV download; the "n/a" caption and both
  uncaught tracebacks are gone at the source rather than caught downstream.
- Multi-section CSV is not a strict RFC 4180 single-table document —
  it is a concatenation with comment lines. This is the standard shape
  for multi-table CSV exports and imports cleanly; consumers wanting one
  clean table per file use the per-section download buttons, which still
  emit exactly one section each.
- `ReportingError` remains for genuinely unsupported formats, which is
  the only case where refusing is the honest answer.
