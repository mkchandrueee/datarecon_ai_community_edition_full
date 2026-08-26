# datarecon/presentation/views/test_suites_view.py — saved, re-runnable
# validation configurations (regression testing; see ADR-0005).
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.domain.entities.test_suite import TestSuite
from datarecon.presentation.components.report_export import (
    render_csv_download_button,
    render_export_buttons,
)
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.summary_table import render_summary_table
from datarecon.presentation.container import ServiceContainer

_ALL_PROJECTS = "All Projects"
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
        st.json(other_params)


def _render_module_reports(container: ServiceContainer, project_id: str | None) -> None:
    """Per-module tables of what each suite last measured, plus a combined
    export — the suite list alone says whether a suite passed, not by how much."""
    reports = container.suite_report_service.module_reports(project_id)
    if not reports:
        return

    st.subheader("Module-wise Report")
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
                key=f"ts_report_csv_{module.name}",
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
    render_export_buttons(container.reporting_service, payload, key_prefix="ts_module_report")


def render(container: ServiceContainer) -> None:
    st.header("Test Suites")
    st.caption(
        "Saved validation configurations you can re-run on demand for regression checks. "
        "Scheduled/automatic execution is planned for a later phase."
    )

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
    table = pd.DataFrame(
        [
            {
                "name": s.name,
                "project": project_name_by_id.get(s.project_id, s.project_id),
                "module": s.module.value,
                "last_run_status": s.last_run_status.value if s.last_run_status else "never run",
                "last_run_at": s.last_run_at,
                "created_at": s.created_at,
            }
            for s in suites
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)

    _render_module_reports(container, project_id)

    st.subheader("Run a Test Suite")
    selected_name = st.selectbox("Test Suite", [s.name for s in suites], key="ts_selected_suite")
    suite = next(s for s in suites if s.name == selected_name)

    if suite.description:
        st.caption(suite.description)
    st.subheader("Test Suite Details")
    _render_suite_details(container, suite)

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
