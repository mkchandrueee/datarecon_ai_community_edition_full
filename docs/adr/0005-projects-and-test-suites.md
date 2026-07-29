# ADR-0005: Projects and Test Suites (saved, re-runnable configurations)

## Status
Accepted

## Context
The Master PRD's Community Edition scope (ADR-0002) does not name a
"Test Suite" or "Project" concept — every module view only supports
configuring and running a validation once, then re-entering the same
parameters for the next run. The user explicitly asked for a way to save
a configured validation as a named, trackable unit ("test suite"), group
those units under a "project," and re-run them later for regression
checks — with an eye toward scheduled/unattended execution "in a later
phase." Scheduling/orchestration itself (PRD modules in the 20–37 range)
is Enterprise-only per ADR-0002 and requires infrastructure (Celery,
Kubernetes, a scheduler daemon) that contradicts Community Edition's
single-node, Streamlit-process model. This ADR resolves the ambiguity
between "the user wants regression re-runs now" and "the PRD reserves
scheduling for Enterprise" without asking, per the PRD's own instruction.

## Decision
- **Project** (`domain/entities/project.py`) is a simple named grouping
  entity — `project_id, name, description`. A `Default` project is
  seeded on first run so saving a Test Suite never requires creating a
  project first.
- **TestSuite** (`domain/entities/test_suite.py`) stores a named,
  described, re-runnable configuration: `module` (which validation
  service it targets), `config` (the module's Request dataclass,
  serialized to a JSON-safe dict via `dataclasses.asdict`), the
  source/target connection ids used, and `last_run_id/status/at`
  bookkeeping updated each time it's re-run.
- `schedule_cron` and `schedule_enabled` fields exist on `TestSuite` now
  so the storage schema does not need to change when a scheduler is
  added later, but **no code in this codebase reads or acts on them** —
  Community Edition only supports on-demand "Run Now" re-execution
  (`TestSuiteService.run_suite`), not unattended/scheduled execution.
  Building an actual scheduler (a background process that fires
  `run_suite` on a cron) is deferred to a later phase/Enterprise, exactly
  as the user's own phrasing anticipated.
- Saving is supported for the six comparison/validation modules whose
  Request dataclasses are fully reconstructable from a JSON dict: Schema,
  Record Count, Duplicate, Nullability, Aggregation, and Full Data
  Validation (`test_suite_service.RUNNABLE_MODULES`). Profiling and File
  Comparison are exploratory/mode-dispatched and are not included as
  save targets in this iteration.
- Each module view builds its Request object unconditionally from the
  current form state (not only inside the "Run" button's `if` block) so
  a "💾 Save as Test Suite" expander can serialize it at any time,
  independent of whether the user has clicked Run yet.
- Deleting a Project cascades to its Test Suites at the database level
  (`ON DELETE CASCADE`); the `Default` project itself cannot be deleted
  from `ProjectService.delete_project`.

## Consequences
- Users get real regression value today: save a validated configuration
  once, re-run it identically from the new Test Suites page, and see its
  last run status/summary — without re-entering connection ids, queries,
  or thresholds each time.
- No new infrastructure (message queue, scheduler daemon, cron) is
  introduced, keeping Community Edition's single-node deployment story
  intact per ADR-0002.
- When a scheduler is eventually built (Enterprise or a later Community
  phase), it can drive `TestSuiteService.run_suite(suite_id)` directly
  and toggle `schedule_enabled`/`schedule_cron` without a schema
  migration — the groundwork is already in place.
