# datarecon/presentation/views/dashboard_view.py — Module 19: Reconciliation Dashboard
from __future__ import annotations

import streamlit as st

from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.presentation.components.report_export import render_export_buttons
from datarecon.presentation.container import ServiceContainer

_ALL_PROJECTS = "All Projects"


def render(container: ServiceContainer) -> None:
    st.header("Reconciliation Dashboard")

    projects = container.project_service.list_projects()
    project_names = [_ALL_PROJECTS, *[p.name for p in projects]]
    selected_name = st.selectbox("Project", project_names, key="dash_project_filter")
    project_id = None
    if selected_name != _ALL_PROJECTS:
        project_id = next(p.project_id for p in projects if p.name == selected_name)

    widgets = container.dashboard_service.widgets(project_id=project_id)
    if widgets.total_runs == 0:
        scope = "yet" if project_id is None else f"for project '{selected_name}' yet"
        st.info(f"No validation runs {scope}. Run a validation module to populate the dashboard.")
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Runs", f"{widgets.total_runs:,}")
    c2.metric("Passed", f"{widgets.passed:,}")
    c3.metric("Failed", f"{widgets.failed:,}")
    c4.metric("Errored", f"{widgets.errored:,}")
    c5.metric("Pass Rate", f"{widgets.pass_rate_percent:.1f}%")

    st.subheader("Pass Rate Trend")
    trend = container.dashboard_service.pass_rate_trend(project_id=project_id)
    if not trend.empty:
        st.line_chart(trend.set_index("date")["pass_rate_percent"])

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Runs by Module")
        by_module = container.dashboard_service.runs_by_module(project_id=project_id)
        if not by_module.empty:
            st.dataframe(by_module, use_container_width=True, hide_index=True)
            st.bar_chart(by_module.set_index("module")[["passed", "failed", "errored"]])
    with col2:
        st.subheader("Runtime Trend")
        runtime = container.dashboard_service.runtime_trend(project_id=project_id)
        if not runtime.empty:
            st.line_chart(runtime.set_index("started_at")["runtime_seconds"])

    st.divider()
    st.subheader("Project Report")
    st.caption(
        "Overall results for the selected project — the same figures shown above, "
        "as a downloadable report."
    )
    report = container.dashboard_service.project_report(selected_name, project_id=project_id)
    payload = ReportPayload(
        title=f"Project Report - {selected_name}",
        summary=report.summary,
        sections=tuple(ReportSection(title, table) for title, table in report.sections()),
    )
    render_export_buttons(container.reporting_service, payload, key_prefix="dash_project_report")
