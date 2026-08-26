# datarecon/presentation/components/mismatch_styling.py
# Shared red/green cell-highlighting Styler helpers for row-level detail
# grids (Module 6's own drill-down, and Module 18's Reports replay of a
# past run's persisted Mismatches/Matched sections).
from __future__ import annotations

import pandas as pd

MISMATCH_CELL_STYLE = "background-color: #ffcdd2; color: #7a0000"
MATCH_ROW_STYLE = "background-color: #c8e6c9; color: #0a4d0a"


def highlight_mismatched_cells(row: pd.Series) -> list[str]:
    mismatched_columns = {
        c.strip() for c in str(row.get("MISMATCHED_COLUMNS", "")).split(",") if c.strip()
    }
    styles = []
    for col in row.index:
        base = col.removesuffix("_source").removesuffix("_target")
        is_side_column = col.endswith("_source") or col.endswith("_target")
        styles.append(MISMATCH_CELL_STYLE if is_side_column and base in mismatched_columns else "")
    return styles


def style_mismatch(mismatch: pd.DataFrame) -> object:
    return mismatch.style.apply(highlight_mismatched_cells, axis=1)


def style_matched(exact_match: pd.DataFrame) -> object:
    return exact_match.style.apply(lambda row: [MATCH_ROW_STYLE] * len(row), axis=1)
