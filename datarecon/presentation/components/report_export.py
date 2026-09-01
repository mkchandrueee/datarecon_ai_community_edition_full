# datarecon/presentation/components/report_export.py
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.reporting_service import (
    DEFAULT_BATCH_ROWS,
    ReportBatch,
    ReportingError,
    ReportingService,
    ReportPayload,
    ReportSection,
    sanitize_export_name,
)
from datarecon.domain.enums import ReportFormat

_FORMATS = (ReportFormat.EXCEL, ReportFormat.CSV, ReportFormat.PDF, ReportFormat.JSON)

#: Past this many batches a wall of buttons stops being usable, so the batch is
#: picked from a dropdown instead — which also means only the chosen batch is
#: encoded, rather than every batch on every rerun.
_MAX_BATCH_BUTTONS = 12
_BATCHES_PER_ROW = 3


def render_export_buttons(
    reporting: ReportingService, payload: ReportPayload, key_prefix: str
) -> None:
    """Render Excel/CSV/PDF/JSON download buttons for a report payload (Module 18)."""
    cols = st.columns(len(_FORMATS))
    for col, fmt in zip(cols, _FORMATS, strict=True):
        with col:
            try:
                data = reporting.export(payload, fmt)
            except ReportingError:
                st.caption(f"{fmt.value.upper()} n/a")
                continue
            st.download_button(
                f"⬇ {fmt.value.upper()}",
                data=data,
                file_name=f"{sanitize_export_name(payload.title)}.{reporting.file_extension(fmt)}",
                mime=reporting.content_type(fmt),
                key=f"{key_prefix}_export_{fmt.value}",
                use_container_width=True,
            )


def render_csv_download_button(
    reporting: ReportingService, title: str, df: pd.DataFrame, key: str, label: str = "Download CSV"
) -> None:
    """Single-table CSV download for one drill-down tab (e.g. the mismatch grid).

    An empty frame still downloads: its header-only CSV states a real result
    ("no mismatches"), so the button stays live instead of disappearing."""
    payload = ReportPayload(title=title, summary={}, sections=(ReportSection(title, df),))
    data = reporting.export(payload, ReportFormat.CSV)
    st.download_button(
        label,
        data=data,
        file_name=f"{sanitize_export_name(title)}.csv",
        mime=reporting.content_type(ReportFormat.CSV),
        key=key,
    )


def render_detail_csv_downloads(
    reporting: ReportingService,
    name: str,
    df: pd.DataFrame,
    key: str,
    label: str = "Download CSV",
    batch_rows: int = DEFAULT_BATCH_ROWS,
) -> None:
    """CSV download for a row-level extract, split into batches when large.

    Below the threshold this is exactly `render_csv_download_button`. Above it,
    the extract is offered as numbered files — `DV_CUSTOMER_MASTER_PASS_1`,
    `_2`, … — covering every row between them (ADR-0013), because a
    half-million-row single CSV is a file most reviewers cannot open.
    """
    batches = reporting.batch_frame(name, df, batch_rows)
    if len(batches) == 1:
        render_csv_download_button(reporting, name, df, key=key, label=label)
        return

    st.caption(
        f"{len(df):,} rows — over the {batch_rows:,}-row batch size, so the extract is "
        f"split into {len(batches)} files covering every row."
    )
    if len(batches) > _MAX_BATCH_BUTTONS:
        options = [f"{b.name}  ({b.row_range_label})" for b in batches]
        chosen = st.selectbox("Batch", options, key=f"{key}_batch_pick")
        _render_batch_button(reporting, batches[options.index(chosen)], key=f"{key}_batch_one")
        return

    for row_start in range(0, len(batches), _BATCHES_PER_ROW):
        row = batches[row_start : row_start + _BATCHES_PER_ROW]
        cols = st.columns(_BATCHES_PER_ROW)
        for col, batch in zip(cols, row, strict=False):
            with col:
                _render_batch_button(
                    reporting, batch, key=f"{key}_batch_{batch.number}", full_width=True
                )


def _render_batch_button(
    reporting: ReportingService, batch: ReportBatch, key: str, full_width: bool = False
) -> None:
    payload = ReportPayload(
        title=batch.name, summary={}, sections=(ReportSection(batch.name, batch.dataframe),)
    )
    st.download_button(
        f"⬇ {batch.name}",
        data=reporting.export(payload, ReportFormat.CSV),
        file_name=f"{sanitize_export_name(batch.name)}.csv",
        mime=reporting.content_type(ReportFormat.CSV),
        key=key,
        help=f"Batch {batch.number} of {batch.total} — {batch.row_range_label}.",
        use_container_width=full_width,
    )
