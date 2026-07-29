# datarecon/presentation/components/extraction_inputs.py
from __future__ import annotations

import streamlit as st


def extraction_inputs(label_prefix: str, key_prefix: str) -> tuple[str | None, str | None]:
    """Render a table-name / custom-SQL pair. Query wins over table when both are given.

    Returns (query, table).
    """
    table = st.text_input(f"{label_prefix} Table Name", key=f"{key_prefix}_table")
    query = st.text_area(
        f"{label_prefix} Custom SQL (optional, overrides table name)",
        key=f"{key_prefix}_query",
        height=80,
    )
    return (query.strip() or None, table.strip() or None)
