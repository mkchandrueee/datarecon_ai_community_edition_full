# datarecon/presentation/components/sql_assist.py
# The "Generate SQL" button that sits beside each module's extraction inputs.
#
# Writing the same SELECT by hand for both sides of every module is the most
# repetitive part of setting up a validation, and a typo in a column name only
# surfaces when the run fails. This reads the table's real catalog and fills
# the Custom SQL box in, so the query is correct by construction (ADR-0011).
from __future__ import annotations

import streamlit as st

from datarecon.application.services.sql_generation_service import GeneratedSQL
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.extraction_inputs import stage_query
from datarecon.presentation.container import ServiceContainer


def render_sql_assist(
    container: ServiceContainer,
    module: ValidationModule,
    connection_id: str | None,
    key_prefix: str,
    table: str | None,
    label: str = "Generate SQL",
) -> GeneratedSQL | None:
    """Render the generate button for one side of a module's form.

    `table` comes straight from the caller's extraction_inputs() return rather
    than being read back out of session state, so the button enables on the
    same render the user types the name.

    Returns the generated statement so the caller can use what was inferred
    (a primary key for Duplicate, NOT NULL columns for Nullability); returns
    None when nothing was generated on this render.
    """
    table = (table or "").strip()
    clicked = st.button(
        label,
        key=f"{key_prefix}_sql_assist",
        disabled=not (connection_id and table),
        help="Read this table's columns and write the SQL for you.",
        use_container_width=True,
    )
    if not (connection_id and table):
        st.caption("Pick a connection and enter a table name to generate SQL.")
        return None

    if clicked:
        result = container.sql_generation_service.generate(
            connection_id, table, modules=(module,)
        )
        if not result.ok:
            st.session_state.pop(f"{key_prefix}_sql_assist_result", None)
            st.error(result.error)
            return None
        statement = result.statements[0]
        # Staged, not written directly: the SQL box already exists on this run,
        # and Streamlit rejects writes to a live widget's key. extraction_inputs
        # picks this up before creating the box on the next run.
        stage_query(key_prefix, statement.sql)
        st.session_state[f"{key_prefix}_sql_assist_result"] = statement
        st.rerun()

    statement = st.session_state.get(f"{key_prefix}_sql_assist_result")
    if statement is not None and statement.table.casefold() == table.casefold():
        st.caption(f"✅ {statement.note}")
        return statement
    return None
