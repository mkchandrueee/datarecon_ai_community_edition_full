# datarecon/presentation/views/test_suites_view.py — saved, re-runnable
# validation configurations (regression testing; see ADR-0005).
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from datarecon.application.services.scheduler_service import SchedulerError
from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.report_export import render_csv_download_button
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.summary_table import (
    render_params_table,
    render_summary_table,
)
from datarecon.presentation.container import ServiceContainer

_ALL_PROJECTS = "All Projects"
_BULK_RESULTS_KEY = "ts_bulk_results"
_SELECTION_KEY = "ts_bulk_selection"
#: Staged selection, applied before the multiselect is created.
_PENDING_SELECTION_KEY = "ts_bulk_selection_pending"
#: Carries the delete confirmation across the rerun that follows it.
_DELETED_MESSAGE_KEY = "ts_bulk_deleted_message"
_DELETE_ARMED_KEY = "ts_bulk_delete_armed"
#: Carries the schedule confirmation across the rerun that follows saving one.
_SCHEDULE_MESSAGE_KEY = "ts_schedule_message"
_NON_PARAM_KEYS = {
    "name",
    "source_connection_id",
    "target_connection_id",
    "connection_id",
    "source_query",
    "source_table",
    "target_query",
    "target_table",
    "query",
    "table",
}


def _render_extraction(config: dict[str, Any], query_key: str, table_key: str) -> None:
    query = config.get(query_key)
    table = config.get(table_key)
    if query:
        st.caption("SQL Query")
        st.code(query, language="sql")
    elif table:
        st.caption("Table")
        st.code(table, language="text")
    else:
        st.caption("Full table extraction (no query/table override saved)")


def _render_suite_details(container: ServiceContainer, suite: TestSuite) -> None:
    config = suite.config
    connection_names = {
        c.connection_id: c.connection_name for c in container.connection_service.list_connections()
    }
    source_label = connection_names.get(suite.source_connection_id or "", suite.source_connection_id)
    target_label = connection_names.get(suite.target_connection_id or "", suite.target_connection_id)

    if suite.target_connection_id:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Source** — `{source_label or '—'}`")
            _render_extraction(config, "source_query", "source_table")
        with col2:
            st.markdown(f"**Target** — `{target_label or '—'}`")
            _render_extraction(config, "target_query", "target_table")
    else:
        st.markdown(f"**Connection** — `{source_label or '—'}`")
        _render_extraction(config, "query", "table")

    other_params = {k: v for k, v in config.items() if k not in _NON_PARAM_KEYS}
    if other_params:
        st.markdown("**Other parameters**")
        render_params_table(other_params)


def _render_grouped_suites(
    suites: list[TestSuite], project_name_by_id: dict[str, str]
) -> None:
    """Suites grouped by project, then by module.

    A flat list stops being navigable once a team has suites across several
    projects and all six modules; the grouping mirrors how they're actually
    organised and puts each module's suites side by side.
    """
    by_project: dict[str, list[TestSuite]] = {}
    for suite in suites:
        by_project.setdefault(suite.project_id, []).append(suite)

    for project_id, project_suites in sorted(
        by_project.items(), key=lambda kv: project_name_by_id.get(kv[0], kv[0]).casefold()
    ):
        project_label = project_name_by_id.get(project_id, project_id)
        st.markdown(f"### {project_label}  ·  {len(project_suites)} suite(s)")

        by_module: dict[ValidationModule, list[TestSuite]] = {}
        for suite in project_suites:
            by_module.setdefault(suite.module, []).append(suite)

        for module in ValidationModule:  # declaration order keeps layout stable
            module_suites = by_module.get(module)
            if not module_suites:
                continue
            with st.expander(
                f"{module.value} — {len(module_suites)} suite(s)", expanded=True
            ):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Test Suite": s.name,
                                "Last Run Status": (
                                    s.last_run_status.value if s.last_run_status else "never run"
                                ),
                                "Last Run": s.last_run_at,
                                "Created": s.created_at,
                            }
                            for s in sorted(module_suites, key=lambda s: s.name)
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )


def _render_bulk_actions(container: ServiceContainer, suites: list[TestSuite]) -> None:
    """Run or delete several suites at once.

    A suite set generated by Bulk Setup is only useful if it can be executed as
    a set — running four modules across twenty tables one click at a time is
    the problem Bulk Setup was meant to remove.
    """
    st.subheader("Bulk Actions")
    deleted_message = st.session_state.pop(_DELETED_MESSAGE_KEY, None)
    if deleted_message:
        st.success(deleted_message)
    by_name = {s.name: s for s in suites}
    all_names = sorted(by_name)

    # The select-all / clear buttons and the pending write both come *before*
    # the multiselect: Streamlit rejects writes to a widget's own state key
    # once that widget exists in the current run.
    pending = st.session_state.pop(_PENDING_SELECTION_KEY, None)
    if pending is not None:
        st.session_state[_SELECTION_KEY] = [n for n in pending if n in by_name]

    quick1, quick2 = st.columns(2)
    if quick1.button("Select all shown", key="ts_select_all", use_container_width=True):
        st.session_state[_PENDING_SELECTION_KEY] = all_names
        st.rerun()
    if quick2.button("Clear selection", key="ts_clear_selection", use_container_width=True):
        st.session_state[_PENDING_SELECTION_KEY] = []
        st.rerun()

    chosen_names = st.multiselect(
        "Select test suites",
        all_names,
        key=_SELECTION_KEY,
        help="Pick any number of suites to run or delete together.",
    )

    if not chosen_names:
        st.caption("Nothing selected.")
        return

    chosen_ids = [by_name[name].suite_id for name in chosen_names]
    run_col, delete_col = st.columns(2)

    if run_col.button(
        f"▶ Run {len(chosen_ids)} suite(s)", type="primary", key="ts_bulk_run",
        use_container_width=True,
    ):
        with st.spinner(f"Running {len(chosen_ids)} test suite(s)..."):
            outcomes = container.test_suite_service.run_suites(chosen_ids)
        st.session_state[_BULK_RESULTS_KEY] = [
            {
                "Test Suite": o.suite.name,
                "Module": o.suite.module.value,
                "Status": o.status.value,
                "Runtime (s)": o.run.runtime_seconds if o.run else None,
                "Error": o.error_message or "",
            }
            for o in outcomes
        ]

    # Two clicks to delete: the button arms a confirmation rather than
    # destroying a set of suites on a single mis-click.
    if delete_col.button(
        f"🗑 Delete {len(chosen_ids)} suite(s)", key="ts_bulk_delete_arm",
        use_container_width=True,
    ):
        st.session_state[_DELETE_ARMED_KEY] = chosen_ids

    armed = st.session_state.get(_DELETE_ARMED_KEY)
    if armed:
        st.warning(f"Delete {len(armed)} test suite(s)? This cannot be undone.")
        confirm, cancel = st.columns(2)
        if confirm.button("Yes, delete them", key="ts_bulk_delete_confirm"):
            deleted = container.test_suite_service.delete_suites(armed)
            st.session_state.pop(_DELETE_ARMED_KEY, None)
            st.session_state[_PENDING_SELECTION_KEY] = []
            st.session_state[_DELETED_MESSAGE_KEY] = f"Deleted {deleted} test suite(s)."
            st.rerun()
        if cancel.button("Cancel", key="ts_bulk_delete_cancel"):
            st.session_state.pop(_DELETE_ARMED_KEY, None)
            st.rerun()

    results = st.session_state.get(_BULK_RESULTS_KEY)
    if results:
        st.markdown("**Bulk run results**")
        table = pd.DataFrame(results)
        passed = int((table["Status"] == "PASS").sum())
        failed = int((table["Status"] == "FAIL").sum())
        errored = int((table["Status"] == "ERROR").sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Passed", passed)
        c2.metric("Failed", failed)
        c3.metric("Errored", errored)
        st.dataframe(table, use_container_width=True, hide_index=True)
        render_csv_download_button(
            container.reporting_service,
            "Bulk Run Results",
            table,
            key="ts_bulk_results_csv",
            label="Download results CSV",
        )


_CRON_PRESETS = {
    "Every hour": "0 * * * *",
    "Every day at 06:00": "0 6 * * *",
    "Weekdays at 06:00": "0 6 * * 1-5",
    "Every Monday at 07:30": "30 7 * * 1",
    "First of the month at 02:00": "0 2 1 * *",
}


def _render_schedule(container: ServiceContainer, suite: TestSuite) -> None:
    """Attach a cron schedule to a suite for unattended execution (ADR-0014)."""
    scheduler = container.scheduler_service
    with st.expander(
        f"⏰ Schedule — {'enabled' if suite.schedule_enabled else 'not scheduled'}",
        expanded=suite.schedule_enabled,
    ):
        st.caption(
            f"Schedules are read in **{scheduler.timezone_name}** and are executed by the "
            "scheduler process (`python -m datarecon.scheduler`), not by this page."
        )

        preset = st.selectbox(
            "Preset",
            ["Custom", *_CRON_PRESETS],
            key=f"ts_sched_preset_{suite.suite_id}",
            help="Pick a common schedule, or choose Custom and write the cron yourself.",
        )
        default_cron = _CRON_PRESETS.get(preset, suite.schedule_cron or "")
        cron = st.text_input(
            "Cron expression (minute hour day-of-month month day-of-week)",
            value=default_cron,
            key=f"ts_sched_cron_{suite.suite_id}",
            placeholder="0 6 * * 1-5",
        )
        enabled = st.checkbox(
            "Run on this schedule",
            value=suite.schedule_enabled,
            key=f"ts_sched_enabled_{suite.suite_id}",
        )

        # Show what the expression means before it is saved — a cron field is
        # quick to write and hard to read back.
        if cron.strip():
            try:
                upcoming = scheduler.next_runs(cron, 3)
                st.caption(
                    "Next runs: "
                    + ", ".join(m.strftime("%a %d %b %H:%M") for m in upcoming)
                    + f"  ({scheduler.timezone_name})"
                )
            except SchedulerError as exc:
                st.warning(str(exc))

        if st.button("Save schedule", key=f"ts_sched_save_{suite.suite_id}"):
            try:
                scheduler.set_schedule(suite.suite_id, cron, enabled)
            except SchedulerError as exc:
                st.error(str(exc))
            else:
                st.session_state[_SCHEDULE_MESSAGE_KEY] = (
                    f"Schedule saved for '{suite.name}'."
                    if enabled
                    else f"Schedule disabled for '{suite.name}'."
                )
                st.rerun()


def _render_schedule_overview(container: ServiceContainer) -> None:
    """Everything that is scheduled, in one table.

    Per-suite settings answer "when does this run?"; only a combined view
    answers "what runs tonight?", which is the question asked after a failure.
    """
    scheduled = container.scheduler_service.scheduled_suites()
    if not scheduled:
        return

    st.subheader("Schedules")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Test Suite": s.name,
                    "Cron": s.schedule_cron,
                    "Enabled": "Yes" if s.schedule_enabled else "No",
                    "Last Run": s.last_run_at,
                    "Last Status": s.last_run_status.value if s.last_run_status else "never run",
                }
                for s in sorted(scheduled, key=lambda s: s.name)
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Start the runner with `python -m datarecon.scheduler`, or have OS cron / Task "
        "Scheduler call `python -m datarecon.scheduler --once` every minute."
    )


def render(container: ServiceContainer) -> None:
    st.header("Test Suites")
    st.caption(
        "Saved validation configurations you can re-run on demand, in bulk, "
        "or on a schedule."
    )

    schedule_message = st.session_state.pop(_SCHEDULE_MESSAGE_KEY, None)
    if schedule_message:
        st.success(schedule_message)

    projects = container.project_service.list_projects()
    project_names = [_ALL_PROJECTS, *[p.name for p in projects]]
    selected_project_name = st.selectbox("Project", project_names, key="ts_project_filter")

    project_id = None
    if selected_project_name != _ALL_PROJECTS:
        project_id = next(p.project_id for p in projects if p.name == selected_project_name)

    suites = container.test_suite_service.list_suites(project_id)
    if not suites:
        st.info(
            "No test suites saved yet. Save one from any validation module's "
            "'Save as Test Suite' section."
        )
        return

    project_name_by_id = {p.project_id: p.name for p in projects}
    _render_grouped_suites(suites, project_name_by_id)
    _render_schedule_overview(container)
    _render_bulk_actions(container, suites)

    st.subheader("Run a Single Test Suite")
    selected_name = st.selectbox("Test Suite", [s.name for s in suites], key="ts_selected_suite")
    suite = next(s for s in suites if s.name == selected_name)

    if suite.description:
        st.caption(suite.description)
    st.subheader("Test Suite Details")
    _render_suite_details(container, suite)
    _render_schedule(container, suite)

    col1, col2 = st.columns(2)
    if col1.button("▶ Run Now", type="primary", key="ts_run_now"):
        with st.spinner(f"Running '{suite.name}'..."):
            outcome = container.test_suite_service.run_suite(suite.suite_id)
        if outcome.error_message:
            st.error(f"Run failed: {outcome.error_message}")
        else:
            render_status_badge(
                outcome.status, outcome.run.runtime_seconds if outcome.run else None
            )
            if outcome.run:
                render_summary_table(outcome.run.summary)

    if col2.button("🗑 Delete Test Suite", key="ts_delete"):
        container.test_suite_service.delete_suite(suite.suite_id)
        st.success(f"Deleted test suite '{suite.name}'.")
        st.rerun()
