# datarecon/presentation/views/aggregation_view.py — Module 7: Aggregation Validation
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.aggregation_validation_service import (
    AggregationSpec,
    AggregationValidationRequest,
)
from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.application.services.test_suite_service import serialize_request
from datarecon.domain.enums import AggregateFunction, ValidationModule
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.extraction_inputs import extraction_inputs
from datarecon.presentation.components.report_export import render_export_buttons
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.test_suite_save import render_save_suite_section
from datarecon.presentation.container import ServiceContainer

_EMPTY_SPEC_ROWS = pd.DataFrame([{"column": "", "function": AggregateFunction.SUM.value}])


def render(container: ServiceContainer) -> None:
    st.header("Aggregation Validation")
    connections = container.connection_service.list_connections()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Source")
        source_id = connection_picker("Source Connection", connections, key="agg_source")
        source_query, source_table = extraction_inputs("Source", "agg_source")
    with col2:
        st.subheader("Target")
        target_id = connection_picker("Target Connection", connections, key="agg_target")
        target_query, target_table = extraction_inputs("Target", "agg_target")

    st.subheader("Aggregations")
    spec_editor = st.data_editor(
        _EMPTY_SPEC_ROWS,
        num_rows="dynamic",
        column_config={
            "column": st.column_config.TextColumn("Column", required=True),
            "function": st.column_config.SelectboxColumn(
                "Function", options=[f.value for f in AggregateFunction], required=True
            ),
        },
        key="agg_specs",
        use_container_width=True,
    )
    group_by_raw = st.text_input("Group By Columns (comma-separated, optional)", key="agg_group_by")
    tolerance_percent = st.number_input(
        "Tolerance (%)", min_value=0.0, max_value=100.0, value=0.0, key="agg_tolerance"
    )

    aggregations = [
        AggregationSpec(column=row["column"], function=AggregateFunction(row["function"]))
        for row in spec_editor.to_dict(orient="records")
        if row.get("column")
    ]
    group_by = [c.strip() for c in group_by_raw.split(",") if c.strip()]
    request = AggregationValidationRequest(
        source_connection_id=source_id or "",
        target_connection_id=target_id or "",
        aggregations=aggregations,
        source_query=source_query,
        source_table=source_table,
        target_query=target_query,
        target_table=target_table,
        group_by=group_by,
        tolerance_percent=float(tolerance_percent),
    )
    if source_id and target_id:
        render_save_suite_section(
            container,
            ValidationModule.AGGREGATION,
            serialize_request(request),
            key_prefix="aggregation",
            source_connection_id=source_id,
            target_connection_id=target_id,
        )

    if st.button(
        "Run Aggregation Validation", type="primary", disabled=not (source_id and target_id)
    ):
        if source_id is None or target_id is None:
            return
        if not aggregations:
            st.warning("Add at least one aggregation (column + function) before running.")
            return
        try:
            with st.spinner("Comparing aggregates..."):
                result = container.aggregation_service.execute(request)
        except Exception as exc:
            st.error(f"Aggregation validation failed: {exc}")
            return

        render_status_badge(result.status, result.run.runtime_seconds)
        st.dataframe(result.comparison, use_container_width=True, hide_index=True)

        payload = ReportPayload(
            title="Aggregation Validation",
            summary=result.run.summary,
            sections=(ReportSection("Aggregation Comparison", result.comparison),),
        )
        render_export_buttons(container.reporting_service, payload, key_prefix="aggregation")
