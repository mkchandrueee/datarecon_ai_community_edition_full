# ADR-0016: Archive is reversible, delete is not, and extraction is a ZIP

## Status
Accepted — extends ADR-0004 (summary-only metadata) and ADR-0008 (Parquet
detail store) with the retention half of their story.

## Context
Run history grows faster than anything else in the tool, and the scheduler
(ADR-0014) turns that from a slow drift into a nightly increment. Acting on
one run at a time is right for inspecting a failure and useless for the two
things people actually do with a backlog: hand a week of evidence to somebody
else, and clear out the noise so the list is readable again.

Two questions had to be settled.

**Should the existing Archive button just become Delete?** No. They answer
different questions. Archive means "I have dealt with this, stop showing it to
me" — a superseded failure after the fix landed. Delete means "this should not
exist" — a run against the wrong connection, or a year of noise. Collapsing
them would force people to choose between a cluttered list and destroying
their own audit trail.

**What shape should a multi-run extract take?** A single merged CSV cannot
hold runs with different columns, and a single Excel workbook hits the sheet
limit long before the row limit. A ZIP of per-run folders is the only shape
that survives ten runs of four modules.

## Decision
- **Archive stays reversible and touches nothing.** It sets a flag; the
  Parquet detail is left exactly where it was. Restoring is one click.
- **Delete removes the run and its row-level detail together**, and asks
  first — two clicks, with the warning naming Archive as the non-destructive
  alternative. The detail is deleted *before* the metadata row: the row is the
  only thing that knows the Parquet directory exists, so removing it first
  would strand the directory on disk permanently. Losing detail while keeping
  the run is the recoverable direction of that race.
- **Extraction produces a ZIP**: one folder per run holding `summary.csv` and
  a CSV per detail section, plus a top-level `manifest.csv` saying what each
  folder is. Folders are named after the run (`FD_CUSTOMER_MASTER`), not its
  UUID, because the person opening the archive is usually not the person who
  exported it; the run id is appended only when two runs would otherwise
  collide.
- Oversized sections are split inside the ZIP by the same rule as a single
  download (ADR-0013). A 500,000-row CSV is no more openable for being zipped.
- The ZIP is built **on click**, not on every rerun, and held in session state
  so the download button survives the reruns that follow. Packaging a
  selection of large runs is expensive and most selections are never
  downloaded.
- Bulk operations report what they actually did — `BulkRunResult` carries the
  count that succeeded and the ids that no longer existed, rather than assuming
  the request equals the outcome.

## Consequences
- A quarter's evidence for one project is one selection and one download, in a
  layout somebody else can navigate.
- Deletion is genuinely permanent: there is no recycle bin, and a deleted run's
  detail is gone from disk. That is the point of having Archive next to it, and
  the confirmation says so.
- The ZIP is assembled in memory, so a selection spanning millions of rows is
  bounded by RAM. That matches the Community Edition ceiling (ADR-0001);
  streaming to a temp file is the natural fix if it ever bites.
