# datarecon/presentation/views/nullability_view.py — Module 5: Nullability Validation
from __future__ import annotations

import streamlit as st

from datarecon.application.services.nullability_validation_service import (
    NullabilityValidationRequest,
)
from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.application.services.test_suite_service import serialize_request
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.extraction_inputs import extraction_inputs
from datarecon.presentation.components.report_export import render_export_buttons
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.test_suite_save import render_save_suite_section
from datarecon.presentation.container import ServiceContainer


def render(container: ServiceContainer) -> None:
    st.header("Nullability / Completeness Validation")
    connections = container.connection_service.list_connections()

    connection_id = connection_picker("Connection", connections, key="null_connection")
    query, table = extraction_inputs("Source", "null")
    columns_raw = st.text_input(
        "Columns to check (comma-separated, blank = all)", key="null_columns"
    )
    sentinel_raw = st.text_input(
        "Sentinel values (comma-separated)",
        value="N/A, NA, NULL, None, -, -999, 1900-01-01",
        key="null_sentinels",
    )
    threshold = st.slider("Completeness Threshold (%)", 0.0, 100.0, 100.0, key="null_threshold")

    columns = [c.strip() for c in columns_raw.split(",") if c.strip()]
    sentinels = [s.strip() for s in sentinel_raw.split(",") if s.strip()]
    request = NullabilityValidationRequest(
        connection_id=connection_id or "",
        query=query,
        table=table,
        columns=columns,
        sentinel_values=sentinels,
        completeness_threshold_percent=threshold,
    )
    if connection_id:
        render_save_suite_section(
            container,
            ValidationModule.NULLABILITY,
            serialize_request(request),
            key_prefix="nullability",
            source_connection_id=connection_id,
        )

    if st.button("Run Nullability Validation", type="primary", disabled=not connection_id):
        if connection_id is None:
            return
        try:
            with st.spinner("Checking completeness..."):
                result = container.nullability_service.execute(request)
        except Exception as exc:
            st.error(f"Nullability validation failed: {exc}")
            return

        render_status_badge(result.status, result.run.runtime_seconds)
        c1, c2 = st.columns(2)
        c1.metric("Total Rows", f"{result.total_rows:,}")
        c2.metric("Completeness Score", f"{result.completeness_score:.2f}%")
        st.dataframe(result.column_stats, use_container_width=True, hide_index=True)

        payload = ReportPayload(
            title="Nullability Validation",
            summary=result.run.summary,
            sections=(ReportSection("Column Statistics", result.column_stats),),
        )
        render_export_buttons(container.reporting_service, payload, key_prefix="nullability")
