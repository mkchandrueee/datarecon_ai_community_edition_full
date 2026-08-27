# datarecon/presentation/components/extraction_inputs.py
from __future__ import annotations

import streamlit as st

#: Streamlit refuses writes to a widget's own state key once that widget exists
#: in the current run, so anything wanting to fill these boxes (generated SQL,
#: a detected foreign key's parent table) parks the value under a pending key
#: and it is moved into place below, *before* the widgets are created.
PENDING_QUERY_SUFFIX = "_query_pending"
PENDING_TABLE_SUFFIX = "_table_pending"


def stage_query(key_prefix: str, sql: str) -> None:
    """Queue `sql` to appear in this prefix's Custom SQL box on the next run."""
    st.session_state[f"{key_prefix}{PENDING_QUERY_SUFFIX}"] = sql


def stage_table(key_prefix: str, table: str) -> None:
    """Queue `table` to appear in this prefix's Table Name box on the next run."""
    st.session_state[f"{key_prefix}{PENDING_TABLE_SUFFIX}"] = table


def extraction_inputs(label_prefix: str, key_prefix: str) -> tuple[str | None, str | None]:
    """Render a table-name / custom-SQL pair. Query wins over table when both are given.

    Returns (query, table).
    """
    for suffix, widget_key in (
        (PENDING_QUERY_SUFFIX, f"{key_prefix}_query"),
        (PENDING_TABLE_SUFFIX, f"{key_prefix}_table"),
    ):
        pending = st.session_state.pop(f"{key_prefix}{suffix}", None)
        if pending is not None:
            st.session_state[widget_key] = pending

    table = st.text_input(f"{label_prefix} Table Name", key=f"{key_prefix}_table")
    query = st.text_area(
        f"{label_prefix} Custom SQL (optional, overrides table name)",
        key=f"{key_prefix}_query",
        height=80,
    )
    return (query.strip() or None, table.strip() or None)
