# datarecon/presentation/components/mismatch_insights.py
# Puts the explanation above the grid, not below it (ADR-0015).
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.core.mismatch_patterns import (
    MismatchInsight,
    Pattern,
    analyse_mismatches,
    analyse_row_set,
)


def render_mismatch_insights(
    mismatch: pd.DataFrame,
    missing_in_target: pd.DataFrame | None = None,
    extra_in_target: pd.DataFrame | None = None,
    business_keys: list[str] | None = None,
) -> MismatchInsight:
    """Lead with what the differences have in common.

    A reader arriving at a failed run wants the cause, and reading it off a
    grid means scrolling far enough to notice a pattern nobody scrolls that
    far to see. Returned so callers can also put the findings in an export.
    """
    insight = analyse_mismatches(mismatch)
    row_patterns = _row_set_patterns(missing_in_target, extra_in_target, business_keys)

    if not insight.patterns and not row_patterns:
        return insight

    st.subheader("What the differences have in common")
    headline = insight.headline if insight.patterns else row_patterns[0].headline
    st.info(headline)

    for pattern in [*insight.patterns, *row_patterns]:
        if pattern.headline == headline and pattern.detail:
            st.caption(pattern.detail)
            break

    with st.expander("All findings", expanded=False):
        frame = _findings_frame(insight.patterns, row_patterns)
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.caption(
            "Findings are computed from the data itself — every claim of "
            "'exactly' holds for every row counted."
        )
    return insight


def _row_set_patterns(
    missing: pd.DataFrame | None,
    extra: pd.DataFrame | None,
    business_keys: list[str] | None,
) -> list[Pattern]:
    if not business_keys:
        return []
    patterns: list[Pattern] = []
    if missing is not None:
        patterns.extend(analyse_row_set(missing, business_keys, "missing"))
    if extra is not None:
        patterns.extend(analyse_row_set(extra, business_keys, "extra"))
    return patterns


def _findings_frame(patterns: list[Pattern], row_patterns: list[Pattern]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Finding": p.headline,
                "Why it matters": p.detail,
                "Column": p.column or "—",
                "Rows": p.affected_rows,
            }
            for p in [*patterns, *row_patterns]
        ],
        columns=["Finding", "Why it matters", "Column", "Rows"],
    )
