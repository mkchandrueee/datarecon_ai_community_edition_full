# datarecon/presentation/views/profiling_view.py — Module 10: Data Profiling
from __future__ import annotations

import streamlit as st

from datarecon.application.services.profiling_service import ProfilingRequest
from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.extraction_inputs import extraction_inputs
from datarecon.presentation.components.report_export import (
    render_csv_download_button,
    render_export_buttons,
)
from datarecon.presentation.container import ServiceContainer


def render(container: ServiceContainer) -> None:
    st.header("Data Profiling")
    connections = container.connection_service.list_connections()

    connection_id = connection_picker("Connection", connections, key="prof_connection")
    query, table = extraction_inputs("Source", "prof")
    columns_raw = st.text_input(
        "Columns to profile (comma-separated, blank = all)", key="prof_columns"
    )
    top_n = st.slider("Top-N frequent values", 1, 20, 5, key="prof_top_n")

    if st.button("Run Profiling", type="primary", disabled=not connection_id):
        if connection_id is None:
            return
        columns = [c.strip() for c in columns_raw.split(",") if c.strip()]
        request = ProfilingRequest(
            connection_id=connection_id, query=query, table=table, columns=columns, top_n=top_n
        )
        try:
            with st.spinner("Profiling data..."):
                result = container.profiling_service.execute(request)
        except Exception as exc:
            st.error(f"Profiling failed: {exc}")
            return

        st.metric("Total Rows", f"{result.total_rows:,}")
        st.subheader("Column Profiles")
        st.dataframe(result.column_profiles, use_container_width=True, hide_index=True)
        render_csv_download_button(
            container.reporting_service,
            "Column Profiles",
            result.column_profiles,
            key="prof_dl_profiles",
            label="Download profiles CSV",
        )

        st.subheader("Top Values")
        top_value_sections = []
        for col, top_df in result.top_values.items():
            if top_df.empty:
                continue
            with st.expander(col):
                st.dataframe(top_df, use_container_width=True, hide_index=True)
                render_csv_download_button(
                    container.reporting_service,
                    f"Top Values - {col}",
                    top_df,
                    key=f"prof_dl_top_{col}",
                    label="Download top values CSV",
                )
            top_value_sections.append(ReportSection(f"Top Values - {col}", top_df))

        payload = ReportPayload(
            title="Data Profiling",
            summary=result.run.summary,
            sections=(
                ReportSection("Column Profiles", result.column_profiles),
                *top_value_sections,
            ),
        )
        render_export_buttons(container.reporting_service, payload, key_prefix="profiling")
