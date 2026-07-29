# datarecon/presentation/views/schema_view.py — Module 2: Schema Validation
from __future__ import annotations

import streamlit as st

from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.application.services.schema_validation_service import SchemaValidationRequest
from datarecon.application.services.test_suite_service import serialize_request
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.extraction_inputs import extraction_inputs
from datarecon.presentation.components.report_export import render_export_buttons
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.test_suite_save import render_save_suite_section
from datarecon.presentation.container import ServiceContainer


def render(container: ServiceContainer) -> None:
    st.header("Schema Validation")
    connections = container.connection_service.list_connections()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Source")
        source_id = connection_picker("Source Connection", connections, key="schema_source")
        source_query, source_table = extraction_inputs("Source", "schema_source")
    with col2:
        st.subheader("Target")
        target_id = connection_picker("Target Connection", connections, key="schema_target")
        target_query, target_table = extraction_inputs("Target", "schema_target")

    request = SchemaValidationRequest(
        source_connection_id=source_id or "",
        target_connection_id=target_id or "",
        source_query=source_query,
        source_table=source_table,
        target_query=target_query,
        target_table=target_table,
    )
    if source_id and target_id:
        render_save_suite_section(
            container,
            ValidationModule.SCHEMA,
            serialize_request(request),
            key_prefix="schema",
            source_connection_id=source_id,
            target_connection_id=target_id,
        )

    if st.button("Run Schema Validation", type="primary", disabled=not (source_id and target_id)):
        if source_id is None or target_id is None:
            return
        try:
            with st.spinner("Comparing schemas..."):
                result = container.schema_service.execute(request)
        except Exception as exc:
            st.error(f"Schema validation failed: {exc}")
            return

        render_status_badge(result.status, result.run.runtime_seconds)
        c1, c2, c3 = st.columns(3)
        c1.metric("Columns Compared", result.run.summary["columns_compared"])
        c2.metric("Name/Type Mismatches", result.run.summary["mismatches"])
        c3.metric("Length/Key/Default Mismatches", result.run.summary["attribute_mismatches"])
        if result.comparison["length_match"].isna().all():
            st.caption(
                "Length/key column/default comparison needs a table name (not a custom SQL "
                "query) on both sides, on a connection type DataRecon can inspect."
            )
        st.dataframe(result.comparison, use_container_width=True, hide_index=True)

        payload = ReportPayload(
            title="Schema Validation",
            summary=result.run.summary,
            sections=(ReportSection("Column Comparison", result.comparison),),
        )
        render_export_buttons(container.reporting_service, payload, key_prefix="schema")
