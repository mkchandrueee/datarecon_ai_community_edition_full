# datarecon/presentation/components/run_status.py
from __future__ import annotations

import streamlit as st

from datarecon.domain.enums import RunStatus

_ICONS = {RunStatus.PASS: "✅", RunStatus.FAIL: "❌", RunStatus.ERROR: "⚠️"}


def render_status_badge(status: RunStatus, runtime_seconds: float | None = None) -> None:
    icon = _ICONS[status]
    suffix = f" ({runtime_seconds:.2f}s)" if runtime_seconds is not None else ""
    message = f"{icon} {status.value}{suffix}"
    if status == RunStatus.PASS:
        st.success(message)
    elif status == RunStatus.FAIL:
        st.error(message)
    else:
        st.warning(message)
