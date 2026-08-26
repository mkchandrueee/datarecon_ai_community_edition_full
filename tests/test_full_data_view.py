"""Unit tests — full_data_view drill-down helpers (Module 6 presentation)."""

from __future__ import annotations

import pandas as pd

from datarecon.presentation.views.full_data_view import _mismatches_by_column


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
