"""Unit tests — summary_table component (Reports shows metrics, not raw JSON)."""

from __future__ import annotations

from datarecon.presentation.components.summary_table import summary_frame


def test_summary_frame_has_metric_and_value_columns() -> None:
    frame = summary_frame({"source_count": 10})
    assert list(frame.columns) == ["Metric", "Value"]


def test_metric_names_are_humanised() -> None:
    frame = summary_frame({"rows_missing_in_target": 3})
    assert frame["Metric"].iloc[0] == "Rows Missing In Target"


def test_integers_are_thousands_separated() -> None:
    frame = summary_frame({"rows_compared": 1234567})
    assert frame["Value"].iloc[0] == "1,234,567"


def test_whole_floats_lose_their_decimals() -> None:
    frame = summary_frame({"success_percentage": 100.0})
    assert frame["Value"].iloc[0] == "100"


def test_fractional_floats_keep_precision() -> None:
    frame = summary_frame({"variance_percent": 12.3456})
    assert frame["Value"].iloc[0] == "12.3456"


def test_booleans_render_as_yes_no() -> None:
    frame = summary_frame({"nulls_equal": True, "trim_strings": False})
    values = dict(zip(frame["Metric"], frame["Value"], strict=True))
    assert values["Nulls Equal"] == "Yes"
    assert values["Trim Strings"] == "No"


def test_none_renders_as_dash() -> None:
    frame = summary_frame({"error_message": None})
    assert frame["Value"].iloc[0] == "—"


def test_status_is_upper_cased() -> None:
    frame = summary_frame({"status": "pass"})
    assert frame["Value"].iloc[0] == "PASS"


def test_empty_summary_gives_empty_frame_with_columns() -> None:
    frame = summary_frame({})
    assert frame.empty
    assert list(frame.columns) == ["Metric", "Value"]


def test_row_order_follows_the_summary() -> None:
    frame = summary_frame({"b": 1, "a": 2})
    assert list(frame["Metric"]) == ["B", "A"]
