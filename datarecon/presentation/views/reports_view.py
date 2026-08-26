# datarecon/presentation/views/reports_view.py — Module 18: Run history browser
#
# Summary metrics always come from the SQLite metadata store (ADR-0004).
# Row-level detail — when it was retained at execute() time — comes from the
# separate Parquet-backed RunDetailStore (ADR-0008); older runs recorded
# before that store existed (or modules that never produce a DataFrame,
# e.g. File Comparison) simply have nothing to show here.
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.mismatch_styling import style_matched, style_mismatch
from datarecon.presentation.components.report_export import (
    render_csv_download_button,
    render_export_buttons,
)
from datarecon.presentation.container import ServiceContainer

_MODULE_FILTER_ALL = "All Modules"
_ALL_PROJECTS = "All Projects"
_ALL_TEST_SUITES = "All Test Suites"
_STYLED_SECTIONS = {"Mismatches": style_mismatch, "Matched": style_matched}


def render(container: ServiceContainer) -> None:
    st.header("Reports — Run History")

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

    project_id = None
    if selected_project_name != _ALL_PROJECTS:
        project_id = next(p.project_id for p in projects if p.name == selected_project_name)
    module = None if selected_module == _MODULE_FILTER_ALL else ValidationModule(selected_module)
    suite_id = None
    if selected_suite_name != _ALL_TEST_SUITES:
        suite_id = next(s.suite_id for s in suites if s.name == selected_suite_name)

    runs = container.run_repository.list_filtered(
        project_id=project_id, module=module, suite_id=suite_id, limit=limit
    )

    if not runs:
        st.info("No validation runs recorded yet.")
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

    selected_run_id = st.selectbox(
        "Inspect a run", [r.run_id for r in runs], key="reports_selected_run"
    )
    run = next(r for r in runs if r.run_id == selected_run_id)
    st.json(run.summary)

    st.subheader("Row-level detail")
    detail_sections = container.detail_store.load_all(run.run_id)
    report_sections: list[ReportSection] = []
    if not detail_sections:
        st.caption(
            "No row-level detail was retained for this run — it may predate detail "
            "persistence, or its module (e.g. File Comparison) has no row-level output."
        )
    else:
        tabs = st.tabs(list(detail_sections.keys()))
        for tab, (title, df) in zip(tabs, detail_sections.items(), strict=True):
            with tab:
                styler = _STYLED_SECTIONS.get(title)
                if styler is not None and not df.empty:
                    st.dataframe(styler(df), use_container_width=True, hide_index=True)
                else:
                    st.dataframe(df, use_container_width=True, hide_index=True)
                render_csv_download_button(
                    container.reporting_service,
                    title,
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
