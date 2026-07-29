# datarecon/presentation/components/connection_picker.py
from __future__ import annotations

import streamlit as st

from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import ConnectionCategory


def connection_picker(
    label: str,
    connections: list[Connection],
    key: str,
    category: ConnectionCategory | None = None,
) -> str | None:
    """Render a connection dropdown, optionally filtered by category.

    Returns the selected connection_id, or None if no connections match.
    """
    options = [c for c in connections if category is None or c.category == category]
    if not options:
        scope = f" of type {category.value}" if category else ""
        st.warning(f"No connections{scope} defined yet. Create one in the Connections page first.")
        return None
    names = {f"{c.connection_name} ({c.database_type.value})": c.connection_id for c in options}
    selected = st.selectbox(label, list(names), key=key)
    return names[selected]
