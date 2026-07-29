# datarecon/presentation/components/sidebar.py
from __future__ import annotations

import streamlit as st

from config.settings import settings

PAGES = (
    "Dashboard",
    "Connections",
    "Projects",
    "Test Suites",
    "Schema Validation",
    "Record Count Validation",
    "Duplicate Validation",
    "Nullability Validation",
    "Full Data Validation",
    "Aggregation Validation",
    "Data Profiling",
    "File Comparison",
    "Reports",
)


def render_sidebar() -> str:
    with st.sidebar:
        st.title("DataRecon AI")
        st.caption(f"Community Edition v{settings.app_version}")
        page = st.radio("Navigation", PAGES, label_visibility="collapsed")
        st.divider()
        st.caption(f"Dataset limit: {settings.max_records_supported:,} records")
    return page
