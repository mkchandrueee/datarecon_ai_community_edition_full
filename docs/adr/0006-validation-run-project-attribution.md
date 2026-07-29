# ADR-0006: Validation runs are tagged with a project_id

## Status
Accepted

## Context
The Dashboard (Module 19) needed to filter by the Project entity
introduced in ADR-0005, but `ValidationRun` had no relationship to a
Project — only Test Suites did. Two options existed: (a) derive a run's
project by joining back through its source/target `Connection`, which
already has an unrelated pre-existing free-text `project` tag field, or
(b) tag `ValidationRun` itself with the ADR-0005 `Project` entity's
`project_id`. Asked directly, the user chose (b) — the Test Suite/Project
grouping, not the older Connection tag — as the one to build on.

## Decision
- `ValidationRun.project_id: str` defaults to `"default"` (ADR-0005's
  seeded Default project). Every module service's `execute()` gained an
  optional `project_id: str = DEFAULT_PROJECT_ID` parameter, threaded
  into both the success and failure `record_run()` calls.
- Ad-hoc runs launched directly from a module's own page (Schema,
  Record Count, etc. views) don't pass a project — they get `"default"`
  automatically, since those pages have no project picker of their own.
- Runs launched via `TestSuiteService.run_suite()` are tagged with the
  triggering suite's `project_id`, so Test Suite runs and their history
  are automatically attributable to the right project without the module
  services needing to know about Test Suites at all.
- `IValidationRunRepository` gained `list_by_project()`; `SQLiteMetadataDatabase`
  migrates existing `validation_runs` tables in place (`ALTER TABLE ...
  ADD COLUMN project_id ... DEFAULT 'default'`) so upgrading an existing
  local install doesn't require deleting the SQLite file.
- `DashboardService` accepts an optional `project_id` on `widgets()`,
  `pass_rate_trend()`, `runs_by_module()`, and `runtime_trend()`; `None`
  means "all projects" (unchanged prior behavior).

## Consequences
- The Dashboard (both the Streamlit page and the NiceGUI prototype, see
  `nicegui_prototype/`) can scope every widget and chart to one project
  or show everything, using the same backend method regardless of which
  UI renders it.
- The pre-existing `Connection.project` free-text field is untouched and
  remains a separate, unrelated tagging mechanism for connections — this
  ADR does not unify the two "project" concepts; that's a possible future
  cleanup, not done here since it wasn't asked for and would touch
  Connection Management (Module 1) scope.
- A run's project attribution is a point-in-time snapshot: if a Test
  Suite is later moved to a different project (not currently supported —
  there's no "move suite" UI), its historical runs keep whatever
  `project_id` they were recorded with.
