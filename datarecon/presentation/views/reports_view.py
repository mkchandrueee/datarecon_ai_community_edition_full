# datarecon/presentation/views/reports_view.py — Module 18: Run history browser
#
# Summary metrics always come from the SQLite metadata store (ADR-0004) and
# render as a Metric/Value table rather than raw JSON.
# Row-level detail — when it was retained at execute() time — comes from the
# separate Parquet-backed RunDetailStore (ADR-0008); older runs recorded
# before that store existed (or modules that never produce a DataFrame,
# e.g. File Comparison) simply have nothing to show here.
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.reporting_service import (
    ReportPayload,
    ReportSection,
    sanitize_export_name,
)
from datarecon.application.services.test_suite_service import prefixed_name
from datarecon.core.mismatch_patterns import infer_business_keys
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.mismatch_insights import render_mismatch_insights
from datarecon.presentation.components.mismatch_styling import style_matched, style_mismatch
from datarecon.presentation.components.report_export import (
    render_csv_download_button,
    render_detail_csv_downloads,
    render_export_buttons,
)
from datarecon.presentation.components.summary_table import render_summary_table
from datarecon.presentation.container import ServiceContainer

_MODULE_FILTER_ALL = "All Modules"
_ALL_PROJECTS = "All Projects"
_ALL_TEST_SUITES = "All Test Suites"
_STYLED_SECTIONS = {"Mismatches": style_mismatch, "Matched": style_matched}

_RUNS_SELECTION_KEY = "reports_runs_selection"
#: Staged selection, applied before the multiselect widget is created.
_PENDING_RUNS_KEY = "reports_runs_selection_pending"
#: Carries a confirmation across the rerun that follows a bulk action.
_RUNS_MESSAGE_KEY = "reports_runs_message"
_DELETE_ARMED_KEY = "reports_runs_delete_armed"
#: The built ZIP, held so the download button survives Streamlit's reruns.
_ZIP_KEY = "reports_runs_zip"

#: Rows rendered in the on-screen grid. Cell-level highlighting builds CSS per
#: cell, so a half-million-row section would lock the browser up before the
#: user ever reached the download buttons. The full extract is in the
#: downloads below the grid — the cap is on the preview only.
_MAX_DISPLAY_ROWS = 5_000


def _render_detail_grid(title: str, df: pd.DataFrame) -> None:
    shown = df.head(_MAX_DISPLAY_ROWS)
    styler = _STYLED_SECTIONS.get(title)
    if styler is not None and not shown.empty:
        st.dataframe(styler(shown), use_container_width=True, hide_index=True)
    else:
        st.dataframe(shown, use_container_width=True, hide_index=True)
    if len(df) > _MAX_DISPLAY_ROWS:
        st.caption(
            f"Previewing the first {_MAX_DISPLAY_ROWS:,} of {len(df):,} rows. "
            "All rows are in the download(s) below."
        )


def render(container: ServiceContainer) -> None:
    """All reporting lives here: per-run history and the module-wise rollup
    of what each Test Suite last measured."""
    st.header("Reports")
    tab_history, tab_modules = st.tabs(["Run History", "Module-wise Report"])
    with tab_history:
        _render_run_history(container)
    with tab_modules:
        _render_module_reports(container)


def _render_module_reports(container: ServiceContainer) -> None:
    """Per-module tables of what each suite last measured, plus a combined
    export — the suite list alone says whether a suite passed, not by how much."""
    projects = container.project_service.list_projects()
    project_names = [_ALL_PROJECTS, *[p.name for p in projects]]
    selected_name = st.selectbox("Project", project_names, key="reports_modules_project")
    project_id = (
        None
        if selected_name == _ALL_PROJECTS
        else next(p.project_id for p in projects if p.name == selected_name)
    )

    reports = container.suite_report_service.module_reports(project_id)
    if not reports:
        st.info(
            "No test suites saved yet. Save one from any validation module's "
            "'Save as Test Suite' section."
        )
        return

    for report in reports:
        module = report.module
        with st.expander(
            f"{module.value} — {report.suite_count} suite(s), "
            f"{report.passed} passed / {report.failed} failed",
            expanded=True,
        ):
            st.dataframe(report.table, use_container_width=True, hide_index=True)
            render_csv_download_button(
                container.reporting_service,
                f"{module.code}_Report",
                report.table,
                key=f"reports_module_csv_{module.name}",
                label=f"Download {module.code} CSV",
            )

    payload = ReportPayload(
        title="Test Suite Module Report",
        summary={
            "modules": len(reports),
            "suites": sum(r.suite_count for r in reports),
            "passed": sum(r.passed for r in reports),
            "failed": sum(r.failed for r in reports),
        },
        sections=tuple(ReportSection(r.module.value, r.table) for r in reports),
    )
    st.caption("Combined report — all modules above")
    render_export_buttons(container.reporting_service, payload, key_prefix="reports_module_report")


def _render_insights(sections: dict[str, pd.DataFrame]) -> None:
    """Explain a stored full-data result, the same as a live one.

    The question "why did this fail?" is asked far more often about a run from
    last night than about one just executed.
    """
    mismatch = sections.get("Mismatches")
    if mismatch is None:
        return
    render_mismatch_insights(
        mismatch,
        sections.get("Missing in Target"),
        sections.get("Extra in Target"),
        infer_business_keys(mismatch),
    )


def _run_label(run) -> str:
    """A label a person can pick from a list — the UUID alone tells nobody
    which run they are looking at."""
    when = run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "—"
    return f"{run.module.code} · {run.name} · {run.status.value} · {when} · {run.run_id[:8]}"


def _render_bulk_run_actions(container: ServiceContainer, runs: list) -> None:
    """Extract, archive or delete several runs at once (ADR-0016).

    Run history grows faster than anything else here — every scheduled tick
    adds to it. One-at-a-time is right for inspecting a failure and useless
    for the two things people do with a backlog: hand over a week of evidence,
    and clear out the noise.
    """
    st.subheader("Bulk Actions")
    message = st.session_state.pop(_RUNS_MESSAGE_KEY, None)
    if message:
        st.success(message)

    by_label = {_run_label(r): r for r in runs}
    labels = list(by_label)

    # Both quick buttons and the staged write come *before* the multiselect:
    # Streamlit rejects writes to a widget's own key once it exists this run.
    pending = st.session_state.pop(_PENDING_RUNS_KEY, None)
    if pending is not None:
        st.session_state[_RUNS_SELECTION_KEY] = [x for x in pending if x in by_label]

    quick1, quick2 = st.columns(2)
    if quick1.button("Select all shown", key="reports_select_all", use_container_width=True):
        st.session_state[_PENDING_RUNS_KEY] = labels
        st.rerun()
    if quick2.button("Clear selection", key="reports_clear_selection", use_container_width=True):
        st.session_state[_PENDING_RUNS_KEY] = []
        st.rerun()

    chosen_labels = st.multiselect(
        "Select runs",
        labels,
        key=_RUNS_SELECTION_KEY,
        help="Pick any number of runs to extract, archive or delete together.",
    )
    if not chosen_labels:
        st.caption("Nothing selected.")
        return

    chosen = [by_label[label] for label in chosen_labels]
    chosen_ids = [r.run_id for r in chosen]
    service = container.run_management_service

    extract_col, archive_col, delete_col = st.columns(3)
    with extract_col:
        # Built on click rather than on every rerun: a selection of large runs
        # is expensive to zip and usually nobody downloads it.
        if st.button(
            f"⬇ Build extract ({len(chosen_ids)})", type="primary",
            key="reports_build_zip", use_container_width=True,
        ):
            with st.spinner(f"Packaging {len(chosen_ids)} run(s)..."):
                st.session_state[_ZIP_KEY] = (
                    service.export_filename(len(chosen_ids)),
                    service.build_export(chosen_ids),
                )

    restoring = all(r.archived for r in chosen)
    with archive_col:
        label = "Restore" if restoring else "Archive"
        if st.button(
            f"{label} {len(chosen_ids)} run(s)", key="reports_bulk_archive",
            use_container_width=True,
        ):
            result = service.archive_runs(chosen_ids, archived=not restoring)
            st.session_state[_PENDING_RUNS_KEY] = []
            st.session_state[_RUNS_MESSAGE_KEY] = (
                f"{label}d {result.succeeded} run(s)."
            )
            st.rerun()

    # Two clicks to delete: archiving is reversible and deletion is not, so
    # the destructive option asks before it acts.
    with delete_col:
        if st.button(
            f"🗑 Delete {len(chosen_ids)} run(s)", key="reports_bulk_delete_arm",
            use_container_width=True,
        ):
            st.session_state[_DELETE_ARMED_KEY] = chosen_ids

    armed = st.session_state.get(_DELETE_ARMED_KEY)
    if armed:
        st.warning(
            f"Permanently delete {len(armed)} run(s) and their row-level detail? "
            "This cannot be undone — Archive hides a run without losing it."
        )
        confirm, cancel = st.columns(2)
        if confirm.button("Yes, delete permanently", key="reports_bulk_delete_confirm"):
            result = service.delete_runs(armed)
            st.session_state.pop(_DELETE_ARMED_KEY, None)
            st.session_state.pop(_ZIP_KEY, None)
            st.session_state[_PENDING_RUNS_KEY] = []
            st.session_state[_RUNS_MESSAGE_KEY] = f"Deleted {result.succeeded} run(s)."
            st.rerun()
        if cancel.button("Cancel", key="reports_bulk_delete_cancel"):
            st.session_state.pop(_DELETE_ARMED_KEY, None)
            st.rerun()

    packaged = st.session_state.get(_ZIP_KEY)
    if packaged:
        filename, payload = packaged
        st.download_button(
            f"⬇ Download {filename} ({len(payload) / 1_048_576:.1f} MB)",
            data=payload,
            file_name=filename,
            mime="application/zip",
            key="reports_download_zip",
        )
        st.caption(
            "One folder per run holding its summary and row-level detail, plus a "
            "manifest naming what each folder is."
        )


def _render_run_history(container: ServiceContainer) -> None:
    projects = container.project_service.list_projects()
    suites = container.test_suite_service.list_suites()
    project_names = [_ALL_PROJECTS, *[p.name for p in projects]]
    module_names = [_MODULE_FILTER_ALL, *[m.value for m in ValidationModule]]
    suite_names = [_ALL_TEST_SUITES, *[s.name for s in suites]]

    col1, col2, col3 = st.columns(3)
    with col1:
        selected_project_name = st.selectbox("Project", project_names, key="reports_project_filter")
    with col2:
        selected_module = st.selectbox("Module", module_names, key="reports_module_filter")
    with col3:
        selected_suite_name = st.selectbox(
            "Test Suite", suite_names, key="reports_suite_filter"
        )
    limit = st.slider("Rows to show", 10, 500, 100, key="reports_limit")
    include_archived = st.checkbox(
        "Include archived runs",
        value=False,
        key="reports_include_archived",
        help="Archived runs stay in history but are hidden here by default.",
    )

    project_id = None
    if selected_project_name != _ALL_PROJECTS:
        project_id = next(p.project_id for p in projects if p.name == selected_project_name)
    module = None if selected_module == _MODULE_FILTER_ALL else ValidationModule(selected_module)
    suite_id = None
    if selected_suite_name != _ALL_TEST_SUITES:
        suite_id = next(s.suite_id for s in suites if s.name == selected_suite_name)

    runs = container.run_repository.list_filtered(
        project_id=project_id,
        module=module,
        suite_id=suite_id,
        limit=limit,
        include_archived=include_archived,
    )

    if not runs:
        st.info("No validation runs match these filters.")
        return

    project_name_by_id = {p.project_id: p.name for p in projects}
    suite_name_by_id = {s.suite_id: s.name for s in suites}
    table = pd.DataFrame(
        [
            {
                "run_id": r.run_id,
                "project": project_name_by_id.get(r.project_id, r.project_id),
                "test_suite": suite_name_by_id.get(r.suite_id, "—") if r.suite_id else "—",
                "module": r.module.value,
                "name": r.name,
                "status": r.status.value,
                "started_at": r.started_at,
                "runtime_seconds": r.runtime_seconds,
                "archived": "Yes" if r.archived else "",
                "error_message": r.error_message or "",
            }
            for r in runs
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    render_csv_download_button(
        container.reporting_service,
        "Run History",
        table,
        key="reports_dl_history",
        label="Download visible history CSV",
    )

    _render_bulk_run_actions(container, runs)

    st.subheader("Inspect a Run")
    selected_run_id = st.selectbox(
        "Inspect a run", [r.run_id for r in runs], key="reports_selected_run"
    )
    run = next(r for r in runs if r.run_id == selected_run_id)

    # Archiving is manual and reversible: a superseded failure can be taken out
    # of the default view once it's been re-run and fixed, without losing it.
    if run.archived:
        st.info("This run is archived — it's hidden from the default view.")
        if st.button("Restore run", key="reports_unarchive"):
            container.run_repository.set_archived(run.run_id, False)
            st.rerun()
    elif st.button("Archive run", key="reports_archive"):
        container.run_repository.set_archived(run.run_id, True)
        st.rerun()

    st.subheader("Summary")
    render_summary_table(run.summary)
    if run.error_message:
        st.error(run.error_message)

    st.subheader("Row-level detail")
    detail_sections = container.detail_store.load_all(run.run_id)
    report_sections: list[ReportSection] = []
    if not detail_sections:
        st.caption(
            "No row-level detail was retained for this run — it may predate detail "
            "persistence, or its module (e.g. File Comparison) has no row-level output."
        )
    else:
        _render_insights(detail_sections)

        # Extracts are named after what produced them, so a downloaded file is
        # still identifiable a week later: DV_CUSTOMER_MASTER_Mismatches.csv.
        run_label = sanitize_export_name(prefixed_name(run.module, run.name))
        tabs = st.tabs(list(detail_sections.keys()))
        for tab, (title, df) in zip(tabs, detail_sections.items(), strict=True):
            with tab:
                _render_detail_grid(title, df)
                render_detail_csv_downloads(
                    container.reporting_service,
                    f"{run_label}_{title}",
                    df,
                    key=f"reports_dl_detail_{selected_run_id}_{title}",
                    label=f"Download {title} CSV",
                )
            report_sections.append(ReportSection(title, df))

    payload = ReportPayload(
        title=f"{run.module.value} - {run.name}",
        summary=run.summary,
        sections=tuple(report_sections),
    )
    render_export_buttons(container.reporting_service, payload, key_prefix="reports_history")
