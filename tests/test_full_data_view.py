"""Unit tests — full_data_view drill-down helpers (Module 6 presentation)."""

from __future__ import annotations

import pandas as pd

from datarecon.presentation.views.full_data_view import (
    _MATCH_ROW_STYLE,
    _MISMATCH_CELL_STYLE,
    _highlight_mismatched_cells,
    _mismatches_by_column,
    _style_matched,
    _style_mismatch,
)


def test_mismatches_by_column_counts_each_column() -> None:
    mismatch = pd.DataFrame(
        {
            "customer_id": [1, 2, 3],
            "MISMATCHED_COLUMNS": ["email,balance", "email", "balance"],
        }
    )
    counts = _mismatches_by_column(mismatch)
    assert counts["email"] == 2
    assert counts["balance"] == 2


def test_mismatches_by_column_empty_dataframe() -> None:
    assert _mismatches_by_column(pd.DataFrame()).empty


def test_mismatches_by_column_missing_column() -> None:
    df = pd.DataFrame({"customer_id": [1, 2]})
    assert _mismatches_by_column(df).empty


def test_mismatches_by_column_handles_blank_entries() -> None:
    mismatch = pd.DataFrame({"MISMATCHED_COLUMNS": ["email", ""]})
    counts = _mismatches_by_column(mismatch)
    assert counts["email"] == 1
    assert len(counts) == 1


def test_highlight_mismatched_cells_marks_only_differing_side_columns() -> None:
    row = pd.Series(
        {
            "customer_id": 1,
            "email_source": "a@x.com",
            "email_target": "b@x.com",
            "balance_source": 10,
            "balance_target": 10,
            "MISMATCHED_COLUMNS": "email",
        }
    )
    styles = _highlight_mismatched_cells(row)
    by_col = dict(zip(row.index, styles, strict=True))
    assert by_col["email_source"] == _MISMATCH_CELL_STYLE
    assert by_col["email_target"] == _MISMATCH_CELL_STYLE
    assert by_col["balance_source"] == ""
    assert by_col["balance_target"] == ""
    assert by_col["customer_id"] == ""
    assert by_col["MISMATCHED_COLUMNS"] == ""


def test_highlight_mismatched_cells_no_mismatches() -> None:
    row = pd.Series({"a_source": 1, "a_target": 1, "MISMATCHED_COLUMNS": ""})
    assert all(s == "" for s in _highlight_mismatched_cells(row))


def test_style_mismatch_produces_a_styler_with_expected_css() -> None:
    mismatch = pd.DataFrame(
        {
            "id": [1],
            "email_source": ["a@x.com"],
            "email_target": ["b@x.com"],
            "MISMATCHED_COLUMNS": ["email"],
        }
    )
    styler = _style_mismatch(mismatch)
    rendered = styler.to_html()
    assert _MISMATCH_CELL_STYLE.split(":")[0] in rendered  # sanity: css property emitted


def test_style_matched_highlights_every_row_green() -> None:
    exact_match = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    styler = _style_matched(exact_match)
    rendered = styler.to_html()
    assert _MATCH_ROW_STYLE.split(":")[0] in rendered
