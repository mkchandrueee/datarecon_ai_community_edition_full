# datarecon/presentation/components/report_export.py
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.reporting_service import (
    ReportingError,
    ReportingService,
    ReportPayload,
    ReportSection,
)
from datarecon.domain.enums import ReportFormat

_FORMATS = (ReportFormat.EXCEL, ReportFormat.CSV, ReportFormat.PDF, ReportFormat.JSON)


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
                file_name=f"{payload.title.replace(' ', '_')}.{reporting.file_extension(fmt)}",
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
        file_name=f"{title.replace(' ', '_')}.csv",
        mime=reporting.content_type(ReportFormat.CSV),
        key=key,
    )
