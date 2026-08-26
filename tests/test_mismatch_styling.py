"""Unit tests — shared mismatch/match Styler helpers (Module 6 + Module 18 reuse)."""

from __future__ import annotations

import pandas as pd

from datarecon.presentation.components.mismatch_styling import (
    MATCH_ROW_STYLE,
    MISMATCH_CELL_STYLE,
    highlight_mismatched_cells,
    style_matched,
    style_mismatch,
)


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
    styles = highlight_mismatched_cells(row)
    by_col = dict(zip(row.index, styles, strict=True))
    assert by_col["email_source"] == MISMATCH_CELL_STYLE
    assert by_col["email_target"] == MISMATCH_CELL_STYLE
    assert by_col["balance_source"] == ""
    assert by_col["balance_target"] == ""
    assert by_col["customer_id"] == ""
    assert by_col["MISMATCHED_COLUMNS"] == ""


def test_highlight_mismatched_cells_no_mismatches() -> None:
    row = pd.Series({"a_source": 1, "a_target": 1, "MISMATCHED_COLUMNS": ""})
    assert all(s == "" for s in highlight_mismatched_cells(row))


def test_style_mismatch_produces_a_styler_with_expected_css() -> None:
    mismatch = pd.DataFrame(
        {
            "id": [1],
            "email_source": ["a@x.com"],
            "email_target": ["b@x.com"],
            "MISMATCHED_COLUMNS": ["email"],
        }
    )
    styler = style_mismatch(mismatch)
    rendered = styler.to_html()
    assert MISMATCH_CELL_STYLE.split(":")[0] in rendered  # sanity: css property emitted


def test_style_matched_highlights_every_row_green() -> None:
    exact_match = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    styler = style_matched(exact_match)
    rendered = styler.to_html()
    assert MATCH_ROW_STYLE.split(":")[0] in rendered
