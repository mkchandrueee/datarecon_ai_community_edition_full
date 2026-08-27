# datarecon/presentation/components/extraction_inputs.py
from __future__ import annotations

import streamlit as st

#: Where render_sql_assist() stages generated SQL. Streamlit refuses writes to a
#: widget's own state key once that widget exists in the current run, so the SQL
#: is parked here and moved into the box below *before* the box is created.
PENDING_QUERY_SUFFIX = "_query_pending"


def extraction_inputs(label_prefix: str, key_prefix: str) -> tuple[str | None, str | None]:
    """Render a table-name / custom-SQL pair. Query wins over table when both are given.

    Returns (query, table).
    """
    pending = st.session_state.pop(f"{key_prefix}{PENDING_QUERY_SUFFIX}", None)
    if pending is not None:
        st.session_state[f"{key_prefix}_query"] = pending

    table = st.text_input(f"{label_prefix} Table Name", key=f"{key_prefix}_table")
    query = st.text_area(
        f"{label_prefix} Custom SQL (optional, overrides table name)",
        key=f"{key_prefix}_query",
        height=80,
    )
    return (query.strip() or None, table.strip() or None)
