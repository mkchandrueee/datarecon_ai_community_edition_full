# datarecon/presentation/views/file_comparison_view.py — Module 13: File Comparison
#
# Only checksum mode has its own service; structure/count/full-data modes
# reuse Schema/RecordCount/FullData validation directly (ADR-0001).
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from datarecon.application.services.file_checksum_service import FileChecksumRequest
from datarecon.application.services.full_data_validation_service import FullValidationRequest
from datarecon.application.services.record_count_service import RecordCountRequest
from datarecon.application.services.reporting_service import ReportPayload, ReportSection
from datarecon.application.services.schema_validation_service import SchemaValidationRequest
from datarecon.domain.enums import ConnectionCategory
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.extraction_inputs import extraction_inputs
from datarecon.presentation.components.report_export import render_export_buttons
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.container import ServiceContainer


@dataclass(frozen=True)
class _Extraction:
    """Table/SQL overrides for whichever side is a database. Both are None for
    a file side, which the services already treat as "read the whole thing"."""

    source_query: str | None = None
    source_table: str | None = None
    target_query: str | None = None
    target_table: str | None = None


_MODES = ("Structure", "Count", "Full Data", "Checksum")

_FILE_TO_FILE = "File ↔ File"
_FILE_TO_TABLE = "File → Table"
_TABLE_TO_FILE = "Table → File"
_DIRECTIONS = (_FILE_TO_FILE, _FILE_TO_TABLE, _TABLE_TO_FILE)


def render(container: ServiceContainer) -> None:
    st.header("File Comparison")
    connections = container.connection_service.list_connections()

    # A file connection is just another Connection (Module 1), and the
    # Schema/Count/FullData services take any pair — so comparing a landed
    # file against the table it was loaded into needs no new engine, only
    # the freedom to pick a database on one side.
    direction = st.radio(
        "Comparison Type", _DIRECTIONS, horizontal=True, key="filecmp_direction"
    )
    source_is_file = direction in (_FILE_TO_FILE, _FILE_TO_TABLE)
    target_is_file = direction in (_FILE_TO_FILE, _TABLE_TO_FILE)

    mode_options = _MODES if (source_is_file and target_is_file) else _MODES[:-1]
    mode = st.radio("Comparison Mode", mode_options, horizontal=True, key="filecmp_mode")
    if not (source_is_file and target_is_file):
        st.caption("Checksum compares whole files byte-for-byte, so it needs a file on both sides.")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Source")
        source_id = connection_picker(
            "Source File" if source_is_file else "Source Connection",
            connections,
            key="filecmp_source",
            category=ConnectionCategory.FILE if source_is_file else None,
        )
        source_query, source_table = (
            (None, None) if source_is_file else extraction_inputs("Source", "filecmp_source")
        )
    with col2:
        st.subheader("Target")
        target_id = connection_picker(
            "Target File" if target_is_file else "Target Connection",
            connections,
            key="filecmp_target",
            category=ConnectionCategory.FILE if target_is_file else None,
        )
        target_query, target_table = (
            (None, None) if target_is_file else extraction_inputs("Target", "filecmp_target")
        )

    extraction = _Extraction(source_query, source_table, target_query, target_table)

    business_keys_raw = ""
    if mode == "Full Data":
        business_keys_raw = st.text_input("Business Key(s), comma-separated", key="filecmp_keys")

    if st.button("Run File Comparison", type="primary", disabled=not (source_id and target_id)):
        if source_id is None or target_id is None:
            return
        try:
            if mode == "Structure":
                _run_structure(container, source_id, target_id, extraction)
            elif mode == "Count":
                _run_count(container, source_id, target_id, extraction)
            elif mode == "Full Data":
                _run_full_data(container, source_id, target_id, business_keys_raw, extraction)
            else:
                _run_checksum(container, source_id, target_id)
        except Exception as exc:
            st.error(f"File comparison failed: {exc}")


def _run_structure(
    container: ServiceContainer, source_id: str, target_id: str, extraction: _Extraction
) -> None:
    result = container.schema_service.execute(
        SchemaValidationRequest(
            source_connection_id=source_id,
            target_connection_id=target_id,
            source_query=extraction.source_query,
            source_table=extraction.source_table,
            target_query=extraction.target_query,
            target_table=extraction.target_table,
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


def _run_count(
    container: ServiceContainer, source_id: str, target_id: str, extraction: _Extraction
) -> None:
    result = container.record_count_service.execute(
        RecordCountRequest(
            source_connection_id=source_id,
            target_connection_id=target_id,
            source_query=extraction.source_query,
            source_table=extraction.source_table,
            target_query=extraction.target_query,
            target_table=extraction.target_table,
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
    container: ServiceContainer,
    source_id: str,
    target_id: str,
    business_keys_raw: str,
    extraction: _Extraction,
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
            source_query=extraction.source_query,
            source_table=extraction.source_table,
            target_query=extraction.target_query,
            target_table=extraction.target_table,
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
