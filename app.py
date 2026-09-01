# app.py
from __future__ import annotations

import streamlit as st

from config.settings import settings
from datarecon.bootstrap import build_container as _build_container
from datarecon.presentation.components.sidebar import render_sidebar
from datarecon.presentation.container import ServiceContainer
from datarecon.presentation.views import (
    aggregation_view,
    bulk_setup_view,
    connections_view,
    dashboard_view,
    duplicate_view,
    file_comparison_view,
    full_data_view,
    nullability_view,
    profiling_view,
    projects_view,
    record_count_view,
    referential_integrity_view,
    reports_view,
    schema_view,
    test_suites_view,
)

_PAGE_RENDERERS = {
    "Dashboard": dashboard_view.render,
    "Schema Validation": schema_view.render,
    "Record Count Validation": record_count_view.render,
    "Duplicate Validation": duplicate_view.render,
    "Nullability Validation": nullability_view.render,
    "Full Data Validation": full_data_view.render,
    "Referential Integrity": referential_integrity_view.render,
    "Aggregation Validation": aggregation_view.render,
    "Data Profiling": profiling_view.render,
    "File Comparison": file_comparison_view.render,
    "Reports": reports_view.render,
    "Projects": projects_view.render,
    "Test Suites": test_suites_view.render,
    "Bulk Setup": bulk_setup_view.render,
}


@st.cache_resource(show_spinner=False)
def build_container() -> ServiceContainer:
    """Cache the composition root for the life of the Streamlit server."""
    return _build_container()


def main() -> None:
    st.set_page_config(
        page_title=settings.app_name,
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    container = build_container()
    if "services" not in st.session_state:
        st.session_state.services = container

    page = render_sidebar()

    if page == "Connections":
        connections_view.render(container.connection_service)
    else:
        _PAGE_RENDERERS[page](container)


if __name__ == "__main__":
    main()
