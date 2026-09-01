# ADR-0013: Row-level extracts are downloaded in numbered batches

## Status
Accepted

## Context
A Full Data Validation over a five-lakh-row table can produce a mismatch set
of the same order. Two things break at that size, and both break silently:

- **The download.** A single CSV of half a million wide rows is hundreds of
  megabytes. Excel refuses past 1,048,576 rows; the xlsx *writer* refuses
  earlier still and raises rather than truncating, so the whole export fails —
  including the sections that would have fitted.
- **The on-screen grid.** The drill-down tabs highlight mismatched cells with a
  pandas `Styler`, which builds CSS per cell. Rendering the full frame locks the
  browser up before the user ever reaches the download buttons.

Neither is a storage problem: `RunDetailStore` (ADR-0008) persists complete
frames with no row cap, so the data is all there. The problem is delivery.

The obvious alternative — cap the extract and say "first 50,000 rows" — was
rejected. A reconciliation report that quietly omits rows is worse than no
report: the reader has no way to know what they didn't see, and the omitted
rows are exactly the ones nobody looked at.

## Decision
- `ReportingService.batch_frame(name, df, batch_rows)` slices a row-level
  extract into `ReportBatch` objects. At or under the threshold (default
  50,000) it returns a single batch under the section's own name, so nothing
  about ordinary downloads changes. Above it, the section becomes `NAME_1`,
  `NAME_2`, … in row order.
- **Batches partition the frame.** Every row appears in exactly one batch, and
  each batch carries its 1-based row range so the reader can see the coverage
  is complete. Batching is about file size, never about dropping rows.
- Excel export splits sections at `EXCEL_MAX_ROWS_PER_SHEET` across numbered
  sheets, using the same mechanism. An oversized section can no longer fail the
  whole workbook.
- Extract names are qualified by the run that produced them —
  `DV_CUSTOMER_MASTER_Mismatches_1.csv`, not `Mismatches.csv` — because a
  downloaded file has to still be identifiable a week later, and two runs would
  otherwise collide in the Downloads folder. `sanitize_export_name()` keeps
  user-supplied suite and table names safe as filenames.
- Beyond `_MAX_BATCH_BUTTONS` batches the UI switches from a button grid to a
  dropdown. That keeps the page usable, and has the useful side effect that
  only the selected batch is encoded on each rerun instead of all of them.
- The on-screen grids preview the first 5,000 rows and say so, naming the
  downloads as the place the full data lives. The cap is on the preview only.

## Consequences
- A high-volume result is now deliverable: ten 50,000-row files a reviewer can
  actually open, instead of one they cannot.
- Batch boundaries are positional, not semantic — a key's rows can straddle two
  files. Row order is the frame's own order, which for Full Data Validation is
  the comparison output order, so related rows generally stay adjacent; nothing
  guarantees it. Anyone re-assembling the full set should concatenate the
  batches rather than treat one as a sample.
- The batch size is a constant rather than a user setting. A per-run control is
  a reasonable later addition; it was left out until there's evidence 50,000 is
  the wrong number for someone.
