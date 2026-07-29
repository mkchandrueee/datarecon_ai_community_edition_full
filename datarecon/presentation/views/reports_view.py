# datarecon/presentation/views/reports_view.py — Module 18: Run history browser
#
# Only summary metrics are available here (ADR-0004) — row-level detail
# from a past run is not retained; export it from the module's own view
# immediately after running it.
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.reporting_service import ReportPayload
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.report_export import (
    render_csv_download_button,
    render_export_buttons,
)
from datarecon.presentation.container import ServiceContainer

_MODULE_FILTER_ALL = "All Modules"
_ALL_PROJECTS = "All Projects"
_ALL_TEST_SUITES = "All Test Suites"


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

    payload = ReportPayload(title=f"{run.module.value} - {run.name}", summary=run.summary)
    render_export_buttons(container.reporting_service, payload, key_prefix="reports_history")
