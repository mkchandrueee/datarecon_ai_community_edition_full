"""Unit tests — mismatch pattern detection (ADR-0015).

The bar for every finding here is that it must be *true*: a wrong explanation
of a reconciliation failure is worse than no explanation, because it sends
someone to fix the wrong system. So each detector is tested both for what it
finds and for what it correctly declines to claim.
"""

from __future__ import annotations

import pandas as pd

from datarecon.core.engine import ComparisonEngine
from datarecon.core.mismatch_patterns import (
    MismatchInsight,
    analyse_mismatches,
    analyse_row_set,
)


def _mismatch_frame(source: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Run the real engine, so the tests exercise the real diff shape."""
    return ComparisonEngine(business_keys=["ID"]).compare(source, target).mismatch


def _kinds(insight: MismatchInsight) -> list[str]:
    return [p.kind for p in insight.patterns]


def _of_kind(insight: MismatchInsight, kind: str):
    return next(p for p in insight.patterns if p.kind == kind)


# ---------- the headline case ----------


def test_a_units_bug_is_reported_as_a_constant_factor() -> None:
    """The case this exists for: 130k rows, one sentence."""
    source = pd.DataFrame({"ID": range(200), "BALANCE": [float(i) + 0.5 for i in range(200)]})
    target = source.assign(BALANCE=source["BALANCE"] * 100)

    insight = analyse_mismatches(_mismatch_frame(source, target))

    ratio = _of_kind(insight, "constant-ratio")
    assert "BALANCE" in ratio.headline
    assert "100x" in ratio.headline
    assert "units" in ratio.detail
    assert ratio.affected_rows == 200


def test_the_headline_is_the_pattern_that_explains_the_most_rows() -> None:
    source = pd.DataFrame(
        {"ID": range(100), "BALANCE": [float(i + 1) for i in range(100)], "NOTE": ["a"] * 100}
    )
    target = source.assign(
        BALANCE=source["BALANCE"] * 100,
        NOTE=["a"] * 95 + ["b"] * 5,
    )

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "BALANCE" in insight.headline


def test_column_concentration_is_reported_with_its_share() -> None:
    source = pd.DataFrame({"ID": range(100), "A": [1] * 100, "B": list(range(100))})
    target = source.assign(A=[2] * 100)

    insight = analyse_mismatches(_mismatch_frame(source, target))

    concentration = _of_kind(insight, "column-concentration")
    assert concentration.column == "A"
    assert concentration.coverage == 1.0


# ---------- numeric patterns ----------


def test_a_constant_offset_is_distinguished_from_a_ratio() -> None:
    source = pd.DataFrame({"ID": range(50), "QTY": [float(i + 10) for i in range(50)]})
    target = source.assign(QTY=source["QTY"] + 7)

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "constant-offset" in _kinds(insight)
    assert "7" in _of_kind(insight, "constant-offset").headline


def test_a_sign_flip_is_named_rather_than_called_a_minus_one_ratio() -> None:
    source = pd.DataFrame({"ID": range(50), "AMOUNT": [float(i + 1) for i in range(50)]})
    target = source.assign(AMOUNT=-source["AMOUNT"])

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "sign-flip" in _kinds(insight)


def test_tiny_differences_are_reported_as_rounding_not_as_an_offset() -> None:
    source = pd.DataFrame({"ID": range(50), "RATE": [1000.0 + i for i in range(50)]})
    target = source.assign(RATE=source["RATE"] + [0.0001 * (i % 3 + 1) for i in range(50)])

    insight = analyse_mismatches(_mismatch_frame(source, target))

    rounding = _of_kind(insight, "rounding")
    assert "tolerance" in rounding.detail


def test_random_numeric_noise_produces_no_false_pattern() -> None:
    """No explanation is better than a wrong one."""
    source = pd.DataFrame({"ID": range(50), "AMOUNT": [float(i) for i in range(50)]})
    target = source.assign(AMOUNT=[float(i * i % 37) + 0.5 for i in range(50)])

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "constant-ratio" not in _kinds(insight)
    assert "constant-offset" not in _kinds(insight)
    assert "rounding" not in _kinds(insight)


def test_a_ratio_is_not_claimed_when_a_differing_source_value_is_zero() -> None:
    """A zero source has no ratio, so no factor can be true of every row."""
    source = pd.DataFrame({"ID": range(10), "AMOUNT": [0.0, *[float(i) for i in range(1, 10)]]})
    target = source.assign(AMOUNT=[5.0, *[float(i) * 100 for i in range(1, 10)]])

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "constant-ratio" not in _kinds(insight)


def test_a_fractional_factor_is_shown_as_a_fraction() -> None:
    source = pd.DataFrame({"ID": range(20), "AMOUNT": [float(i + 1) * 100 for i in range(20)]})
    target = source.assign(AMOUNT=source["AMOUNT"] / 100)

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "1/100" in _of_kind(insight, "constant-ratio").headline


# ---------- string patterns ----------


def test_case_only_differences_point_at_the_ignore_case_option() -> None:
    source = pd.DataFrame({"ID": range(20), "NAME": [f"cust_{i}" for i in range(20)]})
    target = source.assign(NAME=source["NAME"].str.upper())

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "Ignore case" in _of_kind(insight, "case-only").detail


def test_whitespace_only_differences_point_at_the_trim_option() -> None:
    source = pd.DataFrame({"ID": range(20), "NAME": [f"cust_{i}" for i in range(20)]})
    target = source.assign(NAME=source["NAME"] + "  ")

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "Trim strings" in _of_kind(insight, "whitespace-only").detail


def test_truncation_reports_the_target_column_width() -> None:
    source = pd.DataFrame({"ID": range(20), "NAME": [f"CUSTOMER_NUMBER_{i:03}" for i in range(20)]})
    target = source.assign(NAME=source["NAME"].str[:8])

    insight = analyse_mismatches(_mismatch_frame(source, target))

    truncation = _of_kind(insight, "truncation")
    assert "8 characters" in truncation.headline


def test_unrelated_strings_are_not_called_truncation() -> None:
    source = pd.DataFrame({"ID": range(20), "NAME": [f"alpha{i}" for i in range(20)]})
    target = source.assign(NAME=[f"beta{i}" for i in range(20)])

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "truncation" not in _kinds(insight)


# ---------- nulls ----------


def test_a_column_that_arrived_null_is_named_as_such() -> None:
    source = pd.DataFrame({"ID": range(30), "EMAIL": [f"a{i}@b.c" for i in range(30)]})
    target = source.assign(EMAIL=[None] * 30)

    insight = analyse_mismatches(_mismatch_frame(source, target))

    null_pattern = _of_kind(insight, "null-on-target")
    assert "EMAIL" in null_pattern.headline
    assert "dropped or never" in null_pattern.detail


def test_a_column_empty_on_the_source_is_reported_separately() -> None:
    source = pd.DataFrame({"ID": range(30), "EMAIL": [None] * 30})
    target = source.assign(EMAIL=[f"a{i}@b.c" for i in range(30)])

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "null-on-source" in _kinds(insight)


# ---------- timestamps ----------


def test_a_constant_time_shift_is_flagged_as_a_timezone_signature() -> None:
    stamps = pd.to_datetime([f"2026-03-{d:02} 10:00" for d in range(1, 21)])
    source = pd.DataFrame({"ID": range(20), "CREATED": stamps})
    target = source.assign(CREATED=stamps + pd.Timedelta(hours=5, minutes=30))

    insight = analyse_mismatches(_mismatch_frame(source, target))

    shift = _of_kind(insight, "time-shift")
    assert "+5h30m" in shift.headline
    assert "timezone" in shift.detail


def test_an_off_by_one_day_is_named() -> None:
    stamps = pd.to_datetime([f"2026-03-{d:02}" for d in range(1, 21)])
    source = pd.DataFrame({"ID": range(20), "AS_OF": stamps})
    target = source.assign(AS_OF=stamps + pd.Timedelta(days=1))

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "+1 day(s)" in _of_kind(insight, "time-shift").headline


def test_varying_time_differences_are_not_called_a_shift() -> None:
    stamps = pd.to_datetime([f"2026-03-{d:02} 10:00" for d in range(1, 21)])
    source = pd.DataFrame({"ID": range(20), "CREATED": stamps})
    target = source.assign(CREATED=stamps + pd.to_timedelta(range(20), unit="h"))

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "time-shift" not in _kinds(insight)


# ---------- too little evidence ----------


def test_two_rows_are_not_enough_to_claim_a_pattern() -> None:
    """Two rows agreeing on a ratio is a coincidence, not a finding."""
    source = pd.DataFrame({"ID": [1, 2], "AMOUNT": [1.0, 2.0]})
    target = pd.DataFrame({"ID": [1, 2], "AMOUNT": [100.0, 200.0]})

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert "constant-ratio" not in _kinds(insight)


def test_an_empty_mismatch_frame_says_there_is_nothing_to_explain() -> None:
    insight = analyse_mismatches(pd.DataFrame())

    assert insight.total_rows == 0
    assert insight.patterns == []
    assert "No differences" in insight.headline


def test_a_frame_without_the_expected_shape_yields_no_patterns() -> None:
    insight = analyse_mismatches(pd.DataFrame({"a": [1, 2, 3]}))
    assert insight.patterns == []


def test_the_insight_renders_as_a_table() -> None:
    source = pd.DataFrame({"ID": range(20), "AMOUNT": [float(i + 1) for i in range(20)]})
    target = source.assign(AMOUNT=source["AMOUNT"] * 100)

    frame = analyse_mismatches(_mismatch_frame(source, target)).to_frame()

    assert list(frame.columns) == ["Finding", "Detail", "Column", "Rows", "Share of rows"]
    assert not frame.empty


# ---------- missing / extra rows ----------


def test_a_contiguous_block_of_missing_keys_is_called_a_partial_load() -> None:
    missing = pd.DataFrame({"ID": range(90_000, 130_000), "NAME": ["x"] * 40_000})

    patterns = analyse_row_set(missing, ["ID"], "missing")

    assert patterns[0].kind == "contiguous-key-block"
    assert "90,000" in patterns[0].headline and "129,999" in patterns[0].headline
    assert "truncated" in patterns[0].detail


def test_scattered_missing_keys_are_not_called_a_block() -> None:
    missing = pd.DataFrame({"ID": [1, 5, 9, 22, 400], "NAME": ["x"] * 5})

    assert analyse_row_set(missing, ["ID"], "missing") == []


def test_a_composite_key_is_not_analysed_for_contiguity() -> None:
    missing = pd.DataFrame({"A": range(10), "B": range(10)})

    assert analyse_row_set(missing, ["A", "B"], "missing") == []


def test_a_non_numeric_key_is_not_analysed_for_contiguity() -> None:
    missing = pd.DataFrame({"ID": [f"C{i}" for i in range(10)]})

    assert analyse_row_set(missing, ["ID"], "missing") == []


def test_an_empty_row_set_yields_no_patterns() -> None:
    assert analyse_row_set(pd.DataFrame({"ID": []}), ["ID"], "extra") == []


def test_a_specific_cause_outranks_bare_column_concentration() -> None:
    """"Off by exactly 100x" is the answer; "differs in BALANCE" is the address."""
    source = pd.DataFrame({"ID": range(50), "BALANCE": [float(i + 1) for i in range(50)]})
    target = source.assign(BALANCE=source["BALANCE"] * 100)

    insight = analyse_mismatches(_mismatch_frame(source, target))

    assert insight.patterns[0].kind == "constant-ratio"
    assert insight.headline == "BALANCE is off by exactly 100x in the target"
