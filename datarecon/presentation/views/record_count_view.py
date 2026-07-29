# datarecon/presentation/views/record_count_view.py — Module 3: Record Count Validation
from __future__ import annotations

import streamlit as st

from datarecon.application.services.record_count_service import RecordCountRequest
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
    st.header("Record Count Validation")
    connections = container.connection_service.list_connections()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Source")
        source_id = connection_picker("Source Connection", connections, key="rc_source")
        source_query, source_table = extraction_inputs("Source", "rc_source")
    with col2:
        st.subheader("Target")
        target_id = connection_picker("Target Connection", connections, key="rc_target")
        target_query, target_table = extraction_inputs("Target", "rc_target")

    group_by_raw = st.text_input("Group By Columns (comma-separated, optional)", key="rc_group_by")
    c1, c2 = st.columns(2)
    tolerance_absolute = c1.number_input(
        "Tolerance (absolute rows)", min_value=0, value=0, key="rc_tol_abs"
    )
    tolerance_percent = c2.number_input(
        "Tolerance (%)", min_value=0.0, max_value=100.0, value=0.0, key="rc_tol_pct"
    )

    group_by = [c.strip() for c in group_by_raw.split(",") if c.strip()]
    request = RecordCountRequest(
        source_connection_id=source_id or "",
        target_connection_id=target_id or "",
        source_query=source_query,
        source_table=source_table,
        target_query=target_query,
        target_table=target_table,
        group_by=group_by,
        tolerance_absolute=int(tolerance_absolute),
        tolerance_percent=float(tolerance_percent),
    )
    if source_id and target_id:
        render_save_suite_section(
            container,
            ValidationModule.RECORD_COUNT,
            serialize_request(request),
            key_prefix="record_count",
            source_connection_id=source_id,
            target_connection_id=target_id,
        )

    if st.button(
        "Run Record Count Validation", type="primary", disabled=not (source_id and target_id)
    ):
        if source_id is None or target_id is None:
            return
        try:
            with st.spinner("Counting records..."):
                result = container.record_count_service.execute(request)
        except Exception as exc:
            st.error(f"Record count validation failed: {exc}")
            return

        render_status_badge(result.status, result.run.runtime_seconds)
        c1, c2, c3 = st.columns(3)
        c1.metric("Source Count", f"{result.source_count:,}")
        c2.metric("Target Count", f"{result.target_count:,}")
        c3.metric("Variance %", f"{result.variance_percent:.2f}%", delta=result.difference)

        sections = []
        if not result.group_breakdown.empty:
            st.subheader("Group Breakdown")
            st.dataframe(result.group_breakdown, use_container_width=True, hide_index=True)
            sections.append(ReportSection("Group Breakdown", result.group_breakdown))

        payload = ReportPayload(
            title="Record Count Validation", summary=result.run.summary, sections=tuple(sections)
        )
        render_export_buttons(container.reporting_service, payload, key_prefix="record_count")
