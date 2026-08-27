# datarecon/presentation/components/summary_table.py
# Renders a run's summary dict as a readable two-column table instead of raw
# JSON. The summary is a flat dict of metrics, which is exactly a table — JSON
# made the reader parse braces and quotes to find a number.
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

# Keys that carry a PASS/FAIL verdict rather than a measurement.
_STATUS_KEYS = frozenset({"status", "overall_status", "result"})


def summary_frame(summary: dict[str, Any]) -> pd.DataFrame:
    """Turn a summary dict into a tidy Metric/Value frame.

    Metric names are humanised (`rows_missing_in_target` -> `Rows Missing In
    Target`) and numbers are thousands-separated, since these tables are read
    by people rather than parsed.
    """
    rows = [
        {"Metric": _humanise(key), "Value": _format_value(key, value)}
        for key, value in summary.items()
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def render_summary_table(summary: dict[str, Any], caption: str | None = None) -> pd.DataFrame:
    """Render the summary as a table and return the frame that was shown, so
    callers can feed the same data into an export payload."""
    frame = summary_frame(summary)
    if frame.empty:
        st.caption("No summary metrics recorded for this run.")
        return frame
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if caption:
        st.caption(caption)
    return frame


def params_frame(params: dict[str, Any]) -> pd.DataFrame:
    """Turn a saved config dict into a Parameter/Value frame.

    Unlike a run summary, config values can be lists (business keys) or dicts
    (comparison options), so those are flattened into readable text rather
    than shown as Python reprs. Nested dicts become one row per leaf, keyed
    `parent.child`, which keeps the table flat and sortable.
    """
    rows: list[dict[str, str]] = []
    for key, value in params.items():
        if isinstance(value, dict):
            rows.extend(
                {"Parameter": f"{_humanise(key)} — {_humanise(k)}", "Value": _format_value(k, v)}
                for k, v in value.items()
            )
        else:
            rows.append({"Parameter": _humanise(key), "Value": _format_value(key, value)})
    return pd.DataFrame(rows, columns=["Parameter", "Value"])


def render_params_table(params: dict[str, Any]) -> None:
    frame = params_frame(params)
    if frame.empty:
        st.caption("No additional parameters saved.")
        return
    st.dataframe(frame, use_container_width=True, hide_index=True)


def _humanise(key: str) -> str:
    return str(key).replace("_", " ").strip().title()


def _format_value(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        # Percentages and tolerances need their decimals; whole numbers don't.
        return f"{value:,.4f}".rstrip("0").rstrip(".") if value % 1 else f"{int(value):,}"
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        # Business keys, group-by columns, aggregation specs — a comma list
        # reads far better than a Python repr full of brackets and quotes.
        return ", ".join(_format_item(v) for v in value) if value else "—"
    if str(key).casefold() in _STATUS_KEYS:
        return str(value).upper()
    return str(value)


def _format_item(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if v is not None)
    return str(value)
