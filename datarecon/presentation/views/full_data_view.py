# datarecon/presentation/views/full_data_view.py — Module 6: Full Data Validation
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.full_data_validation_service import FullValidationRequest
from datarecon.application.services.reporting_service import (
    ReportPayload,
    ReportSection,
    sanitize_export_name,
)
from datarecon.application.services.test_suite_service import prefixed_name, serialize_request
from datarecon.core.engine import ComparisonConfig
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.extraction_inputs import extraction_inputs
from datarecon.presentation.components.mismatch_styling import style_matched, style_mismatch
from datarecon.presentation.components.report_export import (
    render_detail_csv_downloads,
    render_export_buttons,
)
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.test_suite_save import render_save_suite_section
from datarecon.presentation.container import ServiceContainer

#: Rows rendered in a drill-down grid; the full result is in the downloads.
#: Highlighting is per-cell, so an unbounded grid stalls the browser.
_MAX_DISPLAY_ROWS = 5_000


def _render_drilldown(df: pd.DataFrame, styler=None) -> None:
    shown = df.head(_MAX_DISPLAY_ROWS)
    if styler is not None and not shown.empty:
        st.dataframe(styler(shown), use_container_width=True, hide_index=True)
    else:
        st.dataframe(shown, use_container_width=True, hide_index=True)
    if len(df) > _MAX_DISPLAY_ROWS:
        st.caption(
            f"Previewing the first {_MAX_DISPLAY_ROWS:,} of {len(df):,} rows. "
            "All rows are in the download(s) below."
        )


def _mismatches_by_column(mismatch: pd.DataFrame) -> pd.Series:
    if mismatch.empty or "MISMATCHED_COLUMNS" not in mismatch.columns:
        return pd.Series(dtype="int64")
    exploded = mismatch["MISMATCHED_COLUMNS"].str.split(",").explode().str.strip()
    exploded = exploded[exploded != ""]
    return exploded.value_counts()


def render(container: ServiceContainer) -> None:
    st.header("Full Data Validation")
    connections = container.connection_service.list_connections()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Source")
        source_id = connection_picker("Source Connection", connections, key="fd_source")
        source_query, source_table = extraction_inputs("Source", "fd_source")
    with col2:
        st.subheader("Target")
        target_id = connection_picker("Target Connection", connections, key="fd_target")
        target_query, target_table = extraction_inputs("Target", "fd_target")

    business_keys_raw = st.text_input("Business Key(s), comma-separated", key="fd_keys")
    with st.expander("Comparison Options"):
        c1, c2, c3 = st.columns(3)
        nulls_equal = c1.checkbox("NULL == NULL", value=True, key="fd_nulls_equal")
        trim_strings = c2.checkbox("Trim strings", value=False, key="fd_trim")
        ignore_case = c3.checkbox("Ignore case", value=False, key="fd_case")
        float_tolerance = st.number_input(
            "Float tolerance", min_value=0.0, value=0.0, format="%.6f", key="fd_float_tol"
        )
        drop_duplicate_keys = st.checkbox(
            "Drop duplicate-key rows instead of failing", value=False, key="fd_drop_dups"
        )

    business_keys = [c.strip() for c in business_keys_raw.split(",") if c.strip()]
    config = ComparisonConfig(
        nulls_equal=nulls_equal,
        trim_strings=trim_strings,
        ignore_case=ignore_case,
        float_tolerance=float(float_tolerance),
        drop_duplicate_keys=drop_duplicate_keys,
    )
    request = FullValidationRequest(
        source_connection_id=source_id or "",
        target_connection_id=target_id or "",
        business_keys=business_keys,
        source_query=source_query,
        source_table=source_table,
        target_query=target_query,
        target_table=target_table,
        config=config,
    )
    if source_id and target_id:
        render_save_suite_section(
            container,
            ValidationModule.FULL_DATA,
            serialize_request(request),
            key_prefix="full_data",
            source_connection_id=source_id,
            target_connection_id=target_id,
        )

    if st.button(
        "Run Full Data Validation", type="primary", disabled=not (source_id and target_id)
    ):
        if source_id is None or target_id is None:
            return
        if not business_keys:
            st.warning("At least one business key is required.")
            return
        try:
            with st.spinner("Running full data comparison..."):
                outcome = container.full_data_service.execute(request)
        except Exception as exc:
            st.error(f"Full data validation failed: {exc}")
            return

        result = outcome.result
        render_status_badge(outcome.run.status, outcome.run.runtime_seconds)
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Rows Compared", f"{result.summary['rows_compared']:,}")
        c2.metric("Rows Matched", f"{result.summary['rows_matched']:,}")
        c3.metric("Rows Missing", f"{result.summary['rows_missing_in_target']:,}")
        c4.metric("Rows Extra", f"{result.summary['rows_extra_in_target']:,}")
        c5.metric("Rows Mismatched", f"{result.summary['rows_mismatched']:,}")
        c6.metric("Success Pct", f"{result.summary['success_percentage']:.4f}")

        column_counts = _mismatches_by_column(result.mismatch)
        if not column_counts.empty:
            st.subheader("Mismatches by column")
            st.bar_chart(column_counts)

        st.subheader("Drill-down")
        tab_missing, tab_extra, tab_mismatch, tab_match = st.tabs(
            ["Missing", "Extra", "Mismatch", "Matched"]
        )
        # Downloads are named after the run, so files from two tables don't
        # both land in Downloads as "Mismatch.csv".
        extract_label = sanitize_export_name(
            prefixed_name(ValidationModule.FULL_DATA, outcome.run.name)
        )
        with tab_missing:
            _render_drilldown(result.missing_in_target)
            render_detail_csv_downloads(
                container.reporting_service,
                f"{extract_label}_Missing",
                result.missing_in_target,
                key="fd_dl_missing",
                label="Download missing CSV",
            )
        with tab_extra:
            _render_drilldown(result.extra_in_target)
            render_detail_csv_downloads(
                container.reporting_service,
                f"{extract_label}_Extra",
                result.extra_in_target,
                key="fd_dl_extra",
                label="Download extra CSV",
            )
        with tab_mismatch:
            _render_drilldown(result.mismatch, style_mismatch)
            render_detail_csv_downloads(
                container.reporting_service,
                f"{extract_label}_Mismatch",
                result.mismatch,
                key="fd_dl_mismatch",
                label="Download mismatch CSV",
            )
        with tab_match:
            _render_drilldown(result.exact_match, style_matched)
            render_detail_csv_downloads(
                container.reporting_service,
                f"{extract_label}_Matched",
                result.exact_match,
                key="fd_dl_matched",
                label="Download matched CSV",
            )

        st.divider()
        payload = ReportPayload(
            title="Full Data Validation",
            summary=result.summary,
            sections=(
                ReportSection("Mismatches", result.mismatch),
                ReportSection("Missing in Target", result.missing_in_target),
                ReportSection("Extra in Target", result.extra_in_target),
            ),
        )
        render_export_buttons(container.reporting_service, payload, key_prefix="full_data")
