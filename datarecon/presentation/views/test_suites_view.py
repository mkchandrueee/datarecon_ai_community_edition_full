# datarecon/presentation/views/test_suites_view.py — saved, re-runnable
# validation configurations (regression testing; see ADR-0005).
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.summary_table import (
    render_params_table,
    render_summary_table,
)
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
    _render_grouped_suites(suites, project_name_by_id)

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
