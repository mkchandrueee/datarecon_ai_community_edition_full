# datarecon/presentation/views/file_comparison_view.py — Module 13: File Comparison
#
# Only checksum mode has its own service; structure/count/full-data modes
# reuse Schema/RecordCount/FullData validation directly (ADR-0001).
from __future__ import annotations

import streamlit as st

from datarecon.application.services.file_checksum_service import FileChecksumRequest
from datarecon.application.services.full_data_validation_service import FullValidationRequest
from datarecon.application.services.record_count_service import RecordCountRequest
from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.application.services.schema_validation_service import SchemaValidationRequest
from datarecon.domain.enums import ConnectionCategory
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.report_export import render_export_buttons
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.container import ServiceContainer

_MODES = ("Structure", "Count", "Full Data", "Checksum")


def render(container: ServiceContainer) -> None:
    st.header("File Comparison")
    connections = container.connection_service.list_connections()

    mode = st.radio("Comparison Mode", _MODES, horizontal=True, key="filecmp_mode")
    col1, col2 = st.columns(2)
    with col1:
        source_id = connection_picker(
            "Source File", connections, key="filecmp_source", category=ConnectionCategory.FILE
        )
    with col2:
        target_id = connection_picker(
            "Target File", connections, key="filecmp_target", category=ConnectionCategory.FILE
        )

    business_keys_raw = ""
    if mode == "Full Data":
        business_keys_raw = st.text_input("Business Key(s), comma-separated", key="filecmp_keys")

    if st.button("Run File Comparison", type="primary", disabled=not (source_id and target_id)):
        if source_id is None or target_id is None:
            return
        try:
            if mode == "Structure":
                _run_structure(container, source_id, target_id)
            elif mode == "Count":
                _run_count(container, source_id, target_id)
            elif mode == "Full Data":
                _run_full_data(container, source_id, target_id, business_keys_raw)
            else:
                _run_checksum(container, source_id, target_id)
        except Exception as exc:
            st.error(f"File comparison failed: {exc}")


def _run_structure(container: ServiceContainer, source_id: str, target_id: str) -> None:
    result = container.schema_service.execute(
        SchemaValidationRequest(
            source_connection_id=source_id,
            target_connection_id=target_id,
            name="File Comparison (Structure)",
        )
    )
    render_status_badge(result.status, result.run.runtime_seconds)
    st.dataframe(result.comparison, use_container_width=True, hide_index=True)
    payload = ReportPayload(
        title="File Comparison (Structure)",
        summary=result.run.summary,
        sections=(ReportSection("Column Comparison", result.comparison),),
    )
    render_export_buttons(container.reporting_service, payload, key_prefix="filecmp_structure")


def _run_count(container: ServiceContainer, source_id: str, target_id: str) -> None:
    result = container.record_count_service.execute(
        RecordCountRequest(
            source_connection_id=source_id,
            target_connection_id=target_id,
            name="File Comparison (Count)",
        )
    )
    render_status_badge(result.status, result.run.runtime_seconds)
    c1, c2 = st.columns(2)
    c1.metric("Source Count", f"{result.source_count:,}")
    c2.metric("Target Count", f"{result.target_count:,}")
    payload = ReportPayload(title="File Comparison (Count)", summary=result.run.summary)
    render_export_buttons(container.reporting_service, payload, key_prefix="filecmp_count")


def _run_full_data(
    container: ServiceContainer, source_id: str, target_id: str, business_keys_raw: str
) -> None:
    business_keys = [c.strip() for c in business_keys_raw.split(",") if c.strip()]
    if not business_keys:
        st.warning("At least one business key is required for full-data file comparison.")
        return
    outcome = container.full_data_service.execute(
        FullValidationRequest(
            source_connection_id=source_id,
            target_connection_id=target_id,
            business_keys=business_keys,
            name="File Comparison (Full Data)",
        )
    )
    result = outcome.result
    render_status_badge(outcome.run.status, outcome.run.runtime_seconds)
    st.metric("Success %", f"{result.summary['success_percentage']:.2f}%")
    st.dataframe(result.mismatch, use_container_width=True, hide_index=True)
    payload = ReportPayload(
        title="File Comparison (Full Data)",
        summary=result.summary,
        sections=(ReportSection("Mismatches", result.mismatch),),
    )
    render_export_buttons(container.reporting_service, payload, key_prefix="filecmp_fulldata")


def _run_checksum(container: ServiceContainer, source_id: str, target_id: str) -> None:
    result = container.file_checksum_service.execute(
        FileChecksumRequest(source_connection_id=source_id, target_connection_id=target_id)
    )
    render_status_badge(result.status, result.run.runtime_seconds)
    st.code(
        f"Source (SHA-256): {result.source_checksum}\nTarget (SHA-256): {result.target_checksum}"
    )
    st.write("**Match:**", "✅ Yes" if result.match else "❌ No")
    payload = ReportPayload(title="File Comparison (Checksum)", summary=result.run.summary)
    render_export_buttons(container.reporting_service, payload, key_prefix="filecmp_checksum")
