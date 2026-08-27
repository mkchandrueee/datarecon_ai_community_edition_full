# datarecon/presentation/views/duplicate_view.py — Module 4: Duplicate Validation
from __future__ import annotations

import streamlit as st

from datarecon.application.services.duplicate_validation_service import DuplicateValidationRequest
from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.application.services.test_suite_service import serialize_request
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.extraction_inputs import extraction_inputs
from datarecon.presentation.components.report_export import render_export_buttons
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.sql_assist import render_sql_assist
from datarecon.presentation.components.test_suite_save import render_save_suite_section
from datarecon.presentation.container import ServiceContainer


def render(container: ServiceContainer) -> None:
    st.header("Duplicate Validation")
    connections = container.connection_service.list_connections()

    connection_id = connection_picker("Connection", connections, key="dup_connection")
    query, table = extraction_inputs("Source", "dup")
    generated = render_sql_assist(
        container, ValidationModule.DUPLICATE, connection_id, "dup", table
    )
    # The catalog's primary key is the natural duplicate key, so seed the box
    # with it once — the user stays free to edit or replace it afterwards.
    if generated and generated.suggested_keys and not st.session_state.get("dup_keys"):
        st.session_state["dup_keys"] = ", ".join(generated.suggested_keys)
    key_columns_raw = st.text_input("Key Column(s), comma-separated", key="dup_keys")
    sample_limit = st.number_input(
        "Sample Limit", min_value=10, max_value=100_000, value=1000, key="dup_limit"
    )

    key_columns = [c.strip() for c in key_columns_raw.split(",") if c.strip()]
    request = DuplicateValidationRequest(
        connection_id=connection_id or "",
        key_columns=key_columns,
        query=query,
        table=table,
        sample_limit=int(sample_limit),
    )
    if connection_id:
        render_save_suite_section(
            container,
            ValidationModule.DUPLICATE,
            serialize_request(request),
            key_prefix="duplicate",
            source_connection_id=connection_id,
        )

    if st.button("Run Duplicate Validation", type="primary", disabled=not connection_id):
        if connection_id is None:
            return
        try:
            with st.spinner("Scanning for duplicates..."):
                result = container.duplicate_service.execute(request)
        except Exception as exc:
            st.error(f"Duplicate validation failed: {exc}")
            return

        render_status_badge(result.status, result.run.runtime_seconds)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Rows", f"{result.total_rows:,}")
        c2.metric("Duplicate Keys", f"{result.duplicate_key_count:,}")
        c3.metric("Duplicate %", f"{result.duplicate_percent:.2f}%")

        sections = []
        if not result.duplicates.empty:
            st.subheader(f"Sampled Duplicate Rows (up to {int(sample_limit)})")
            st.dataframe(result.duplicates, use_container_width=True, hide_index=True)
            sections.append(ReportSection("Duplicate Rows", result.duplicates))

        payload = ReportPayload(
            title="Duplicate Validation", summary=result.run.summary, sections=tuple(sections)
        )
        render_export_buttons(container.reporting_service, payload, key_prefix="duplicate")
