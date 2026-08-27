"""Unit tests — summary_table component (Reports shows metrics, not raw JSON)."""

from __future__ import annotations

from datarecon.presentation.components.summary_table import params_frame, summary_frame


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


# ---------- saved-config parameter tables (Test Suites) ----------


def test_params_frame_has_parameter_and_value_columns() -> None:
    frame = params_frame({"tolerance_percent": 0.5})
    assert list(frame.columns) == ["Parameter", "Value"]


def test_params_frame_flattens_lists_into_comma_text() -> None:
    frame = params_frame({"business_keys": ["CUSTOMER_ID", "ORDER_ID"]})
    assert frame["Value"].iloc[0] == "CUSTOMER_ID, ORDER_ID"


def test_params_frame_renders_empty_list_as_dash() -> None:
    frame = params_frame({"group_by": []})
    assert frame["Value"].iloc[0] == "—"


def test_params_frame_expands_nested_dict_into_rows() -> None:
    frame = params_frame({"config": {"nulls_equal": True, "float_tolerance": 0.01}})
    params = dict(zip(frame["Parameter"], frame["Value"], strict=True))
    assert params["Config — Nulls Equal"] == "Yes"
    assert params["Config — Float Tolerance"] == "0.01"


def test_params_frame_formats_list_of_dicts_readably() -> None:
    frame = params_frame(
        {"aggregations": [{"column": "AMOUNT", "function": "SUM", "alias": None}]}
    )
    assert frame["Value"].iloc[0] == "AMOUNT SUM"


def test_params_frame_empty_input() -> None:
    frame = params_frame({})
    assert frame.empty
    assert list(frame.columns) == ["Parameter", "Value"]
