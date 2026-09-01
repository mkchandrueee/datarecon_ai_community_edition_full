# datarecon/core/mismatch_patterns.py
# Explains *why* rows differ instead of only listing that they do (ADR-0015).
#
# A full-data run that reports 130,000 mismatches has answered "how many" and
# left the expensive question — "what happened?" — to a person scrolling a
# grid. Nearly always the answer is one mechanical cause repeated: a units
# change, a truncated load, a timezone shift, a column that arrived NULL.
# These are exactly the shapes a computer can find, and the shapes a reader
# would need thousands of rows to notice.
#
# Clean Architecture layer: core (pure pandas/NumPy, no I/O, no Streamlit).
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_SRC = "_source"
_TGT = "_target"
MISMATCHED_COLUMNS = "MISMATCHED_COLUMNS"

#: Relative tolerance for calling a set of ratios or differences "constant".
#: Float arithmetic never reproduces a ratio exactly, so "exactly 100x" has to
#: mean "within floating-point noise of 100x".
_RTOL = 1e-9

#: A ratio or offset this close to the identity is not a finding.
_IDENTITY_EPS = 1e-12

#: Below this many rows a "they are all…" claim is not worth making — two rows
#: agreeing on a ratio is a coincidence, not a pattern.
_MIN_ROWS_FOR_CLAIM = 3


@dataclass(frozen=True)
class Pattern:
    """One explanation for some share of the differences."""

    kind: str
    headline: str
    detail: str = ""
    column: str | None = None
    affected_rows: int = 0
    #: Share of the analysed rows this explains, 0.0-1.0.
    coverage: float = 0.0

    @property
    def coverage_percent(self) -> float:
        return round(self.coverage * 100, 1)


@dataclass(frozen=True)
class MismatchInsight:
    """The ranked explanations for one comparison result."""

    total_rows: int
    patterns: list[Pattern] = field(default_factory=list)

    @property
    def headline(self) -> str:
        """The single sentence worth putting above the grid."""
        if not self.total_rows:
            return "No differences to explain."
        if not self.patterns:
            return f"{self.total_rows:,} differing row(s) — no single pattern stands out."
        return self.patterns[0].headline

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Finding": p.headline,
                    "Detail": p.detail,
                    "Column": p.column or "—",
                    "Rows": p.affected_rows,
                    "Share of rows": f"{p.coverage_percent}%",
                }
                for p in self.patterns
            ],
            columns=["Finding", "Detail", "Column", "Rows", "Share of rows"],
        )


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def analyse_mismatches(mismatch: pd.DataFrame) -> MismatchInsight:
    """Explain a Full Data Validation mismatch frame.

    Expects the engine's wide diff shape: `<col>_source` / `<col>_target` pairs
    plus a `MISMATCHED_COLUMNS` list per row. Anything else yields no patterns
    rather than a wrong one.
    """
    total = len(mismatch)
    if total == 0 or MISMATCHED_COLUMNS not in mismatch.columns:
        return MismatchInsight(total_rows=total)

    counts = _column_hit_counts(mismatch)
    patterns: list[Pattern] = []

    concentration = _concentration_pattern(counts, total)
    if concentration is not None:
        patterns.append(concentration)

    for column, hits in counts.items():
        source_col, target_col = f"{column}{_SRC}", f"{column}{_TGT}"
        if source_col not in mismatch.columns or target_col not in mismatch.columns:
            continue
        rows = mismatch[mismatch[MISMATCHED_COLUMNS].fillna("").apply(
            lambda text, c=column: c in _split_columns(text)
        )]
        found = _explain_column(column, rows[source_col], rows[target_col], hits, total)
        if found is not None:
            patterns.append(found)

    # Ranked by how much of the result each one accounts for, and at equal
    # coverage by how much it says: "BALANCE is off by exactly 100x" is the
    # answer, "every row differs in BALANCE" only says where to look.
    patterns.sort(key=lambda p: (-p.coverage, _specificity_rank(p), p.column or ""))
    return MismatchInsight(total_rows=total, patterns=patterns)


def infer_business_keys(mismatch: pd.DataFrame) -> list[str]:
    """Recover the business keys from a stored diff frame.

    Reports load detail frames back from Parquet without the request that
    produced them, but the diff shape already names its keys: they are the
    columns that carry no `_source` / `_target` twin.
    """
    if MISMATCHED_COLUMNS not in mismatch.columns:
        return []
    return [
        column
        for column in mismatch.columns
        if column != MISMATCHED_COLUMNS
        and not column.endswith(_SRC)
        and not column.endswith(_TGT)
    ]


def analyse_row_set(frame: pd.DataFrame, business_keys: list[str], side: str) -> list[Pattern]:
    """Explain a set of rows present on one side only (missing / extra).

    A contiguous block of keys is the signature of a truncated or partial load,
    which is a different defect from rows going missing at random — and the one
    the row list itself makes hardest to see.
    """
    total = len(frame)
    if total < _MIN_ROWS_FOR_CLAIM or len(business_keys) != 1:
        return []

    key = business_keys[0]
    if key not in frame.columns:
        return []

    values = pd.to_numeric(frame[key], errors="coerce").dropna()
    if len(values) != total or not float(values.iloc[0]).is_integer():
        return []

    low, high = int(values.min()), int(values.max())
    if values.nunique() != total or (high - low + 1) != total:
        return []

    return [
        Pattern(
            kind="contiguous-key-block",
            headline=(
                f"All {total:,} {side} row(s) form one unbroken block of {key} "
                f"({low:,} to {high:,})"
            ),
            detail=(
                "Rows lost at random do not come out contiguous — a solid range "
                "points at a truncated, partial or interrupted load rather than "
                "row-level failures."
            ),
            column=key,
            affected_rows=total,
            coverage=1.0,
        )
    ]


# --------------------------------------------------------------------------- #
# Column-level detection
# --------------------------------------------------------------------------- #
def _explain_column(
    column: str, source: pd.Series, target: pd.Series, hits: int, total: int
) -> Pattern | None:
    coverage = hits / total if total else 0.0

    for detector in (
        _null_pattern,
        _whitespace_pattern,
        _case_pattern,
        _truncation_pattern,
        _ratio_pattern,
        _offset_pattern,
        _rounding_pattern,
        _time_shift_pattern,
    ):
        found = detector(column, source, target)
        if found is not None:
            return Pattern(
                kind=found[0],
                headline=found[1],
                detail=found[2],
                column=column,
                affected_rows=hits,
                coverage=coverage,
            )
    return None


def _null_pattern(column: str, source: pd.Series, target: pd.Series):
    """A column that arrived empty is a load defect, not a data difference."""
    if source.isna().all() and not target.isna().all():
        return (
            "null-on-source",
            f"{column} is empty on the source for every differing row",
            "The target has a value and the source does not, which usually means "
            "the column was not populated rather than that it changed.",
        )
    if target.isna().all() and not source.isna().all():
        return (
            "null-on-target",
            f"{column} arrived NULL in the target for every differing row",
            "The source has values throughout — the column was dropped or never "
            "written, rather than written incorrectly.",
        )
    return None


def _whitespace_pattern(column: str, source: pd.Series, target: pd.Series):
    left, right = _string_pair(source, target)
    if left is None or right is None:
        return None
    if (left.str.strip() == right.str.strip()).all():
        return (
            "whitespace-only",
            f"{column} differs only in leading/trailing whitespace",
            "The values are otherwise identical. Enabling 'Trim strings' in the "
            "comparison options would classify these as matches.",
        )
    return None


def _case_pattern(column: str, source: pd.Series, target: pd.Series):
    left, right = _string_pair(source, target)
    if left is None or right is None:
        return None
    if (left.str.casefold() == right.str.casefold()).all():
        return (
            "case-only",
            f"{column} differs only in letter case",
            "The values match case-insensitively. Enabling 'Ignore case' in the "
            "comparison options would classify these as matches.",
        )
    return None


def _truncation_pattern(column: str, source: pd.Series, target: pd.Series):
    """Target values that are prefixes of the source: a column-width limit."""
    left, right = _string_pair(source, target)
    if left is None or right is None or len(left) < _MIN_ROWS_FOR_CLAIM:
        return None
    is_prefix = [s.startswith(t) and len(t) < len(s) for s, t in zip(left, right, strict=True)]
    if not all(is_prefix):
        return None

    widths = right.str.len().unique()
    if len(widths) == 1:
        width = int(widths[0])
        return (
            "truncation",
            f"{column} is truncated to {width} characters in the target",
            f"Every target value is the first {width} characters of the source — "
            "the target column is almost certainly narrower than the source.",
        )
    return (
        "truncation",
        f"{column} is truncated in the target",
        "Every target value is a prefix of its source value, at varying lengths.",
    )


def _ratio_pattern(column: str, source: pd.Series, target: pd.Series):
    """The units bug: every target value is the source times one constant."""
    left, right = _numeric_pair(source, target)
    if left is None or right is None or len(left) < _MIN_ROWS_FOR_CLAIM:
        return None
    usable = left != 0
    if not usable.all():
        return None

    ratios = (right / left).to_numpy()
    factor = float(np.median(ratios))
    if abs(factor - 1.0) < _IDENTITY_EPS or not np.allclose(ratios, factor, rtol=_RTOL):
        return None

    if abs(factor + 1.0) < _RTOL:
        return (
            "sign-flip",
            f"{column} has the opposite sign in the target for every differing row",
            "Target = -Source throughout. A sign convention differs between the "
            "two systems (debit/credit, or an inverted adjustment).",
        )

    pretty = _format_factor(factor)
    hint = (
        "A clean power of ten across every row is a units or scale problem — "
        "cents against currency units, or a stray multiplier — not row-level "
        "data corruption."
        if _is_power_of_ten(factor)
        else "The same constant multiplier across every row points at a "
        "conversion or scaling step, not row-level corruption."
    )
    return ("constant-ratio", f"{column} is off by exactly {pretty} in the target", hint)


def _offset_pattern(column: str, source: pd.Series, target: pd.Series):
    left, right = _numeric_pair(source, target)
    if left is None or right is None or len(left) < _MIN_ROWS_FOR_CLAIM:
        return None

    diffs = (right - left).to_numpy()
    offset = float(np.median(diffs))
    if abs(offset) < _IDENTITY_EPS:
        return None
    scale = max(abs(offset), float(np.abs(diffs).max()), 1.0)
    if not np.allclose(diffs, offset, rtol=0, atol=scale * 1e-9):
        return None

    return (
        "constant-offset",
        f"{column} is shifted by exactly {_format_number(offset)} in the target",
        "The same constant is added to every row, which is an adjustment or "
        "an off-by-one applied uniformly rather than scattered errors.",
    )


def _rounding_pattern(column: str, source: pd.Series, target: pd.Series):
    """Differences too small to be real: a precision or rounding mismatch."""
    left, right = _numeric_pair(source, target)
    if left is None or right is None or len(left) < _MIN_ROWS_FOR_CLAIM:
        return None

    diffs = np.abs((right - left).to_numpy())
    if not (diffs > 0).any():
        return None
    largest = float(diffs.max())
    magnitude = float(np.abs(left.to_numpy()).max()) or 1.0
    if largest > 0.5 or largest / magnitude > 1e-4:
        return None

    return (
        "rounding",
        f"{column} differs only beyond the {_decimal_places(largest)} decimal place",
        f"The largest difference is {largest:.10g}. Setting a float tolerance in "
        "the comparison options would classify these as matches.",
    )


def _time_shift_pattern(column: str, source: pd.Series, target: pd.Series):
    left, right = _datetime_pair(source, target)
    if left is None or right is None or len(left) < _MIN_ROWS_FOR_CLAIM:
        return None

    deltas = (right - left).dropna()
    if len(deltas) != len(left) or deltas.nunique() != 1:
        return None
    delta = deltas.iloc[0]
    if delta == pd.Timedelta(0):
        return None

    seconds = delta.total_seconds()
    if abs(seconds) % 3600 == 0 or abs(seconds) % 1800 == 0:
        hint = (
            f"A constant {_format_duration(delta)} shift across every row is the "
            "signature of a timezone difference, not of wrong timestamps."
        )
    elif abs(seconds) == 86400:
        hint = "Every timestamp is exactly one day out — an off-by-one in a date window."
    else:
        hint = "The same constant shift applies to every row."

    return (
        "time-shift",
        f"{column} is shifted by exactly {_format_duration(delta)} in the target",
        hint,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _specificity_rank(pattern: Pattern) -> int:
    """Concentration says where to look; every other finding says what happened."""
    return 1 if pattern.kind == "column-concentration" else 0


def _split_columns(text: str) -> list[str]:
    return [part.strip() for part in str(text).split(",") if part.strip()]


def _column_hit_counts(mismatch: pd.DataFrame) -> dict[str, int]:
    """How many rows each column is responsible for, most-hit first."""
    exploded = (
        mismatch[MISMATCHED_COLUMNS]
        .fillna("")
        .str.split(",")
        .explode()
        .str.strip()
    )
    exploded = exploded[exploded != ""]
    return exploded.value_counts().to_dict()


def _concentration_pattern(counts: dict[str, int], total: int) -> Pattern | None:
    """"93% of mismatches are in BALANCE" — where to look, before why."""
    if not counts or total == 0:
        return None
    column, hits = next(iter(counts.items()))
    coverage = hits / total
    if len(counts) == 1:
        headline = f"Every differing row differs in {column}"
    elif coverage >= 0.5:
        headline = f"{round(coverage * 100, 1)}% of differing rows differ in {column}"
    else:
        return None
    return Pattern(
        kind="column-concentration",
        headline=headline,
        detail=(
            f"{len(counts)} column(s) differ in total: "
            + ", ".join(f"{c} ({n:,})" for c, n in list(counts.items())[:5])
        ),
        column=column,
        affected_rows=hits,
        coverage=coverage,
    )


def _aligned(source: pd.Series, target: pd.Series) -> tuple[pd.Series, pd.Series] | None:
    """Drop rows where either side is null — they are a different finding."""
    keep = source.notna() & target.notna()
    if not keep.any():
        return None
    return source[keep], target[keep]


def _string_pair(source: pd.Series, target: pd.Series):
    pair = _aligned(source, target)
    if pair is None:
        return None, None
    left, right = pair
    if not (_is_stringy(left) and _is_stringy(right)):
        return None, None
    return left.astype(str), right.astype(str)


def _numeric_pair(source: pd.Series, target: pd.Series):
    pair = _aligned(source, target)
    if pair is None:
        return None, None
    left, right = pair
    if not (
        pd.api.types.is_numeric_dtype(left)
        and pd.api.types.is_numeric_dtype(right)
        and not pd.api.types.is_bool_dtype(left)
    ):
        return None, None
    return left.astype("float64"), right.astype("float64")


def _datetime_pair(source: pd.Series, target: pd.Series):
    pair = _aligned(source, target)
    if pair is None:
        return None, None
    left, right = pair
    if not (
        pd.api.types.is_datetime64_any_dtype(left)
        and pd.api.types.is_datetime64_any_dtype(right)
    ):
        return None, None
    return left, right


def _is_stringy(series: pd.Series) -> bool:
    return pd.api.types.is_string_dtype(series) or (
        series.dtype == object and all(isinstance(v, str) for v in series)
    )


def _is_power_of_ten(factor: float) -> bool:
    if factor <= 0:
        return False
    exponent = np.log10(factor)
    return bool(abs(exponent - round(exponent)) < 1e-9 and round(exponent) != 0)


def _format_factor(factor: float) -> str:
    if abs(factor) >= 1 or factor == 0:
        return f"{_format_number(factor)}x"
    inverse = 1 / factor
    if abs(inverse - round(inverse)) < 1e-9:
        return f"1/{_format_number(inverse)} ({_format_number(factor)}x)"
    return f"{_format_number(factor)}x"


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{round(value):,}"
    return f"{value:,.6g}"


def _format_duration(delta: pd.Timedelta) -> str:
    seconds = delta.total_seconds()
    sign = "-" if seconds < 0 else "+"
    seconds = abs(seconds)
    if seconds % 86400 == 0:
        return f"{sign}{int(seconds // 86400)} day(s)"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if minutes:
        return f"{sign}{int(hours)}h{int(minutes):02d}m"
    return f"{sign}{int(hours)} hour(s)"


def _decimal_places(largest: float) -> str:
    places = max(1, int(np.ceil(-np.log10(largest))))
    ordinals = {1: "1st", 2: "2nd", 3: "3rd"}
    return ordinals.get(places, f"{places}th")
