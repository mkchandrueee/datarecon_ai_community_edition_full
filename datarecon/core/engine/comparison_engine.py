"""
DataRecon AI — Community Edition
Core Comparison Engine (Module 6: Full Data Validation, Module 32: High Volume Execution)

Clean Architecture layer: core/engine (framework-agnostic domain logic).
No Streamlit, SQLite, or I/O dependencies — pure Pandas/NumPy computation.

Design notes
------------
- Fully vectorized: outer merge with indicator for the set split
  (missing / extra), then a column-wise vectorized equality mask for the
  match / mismatch split. No iterrows, no per-row Python callbacks.
- Column-wise NumPy comparison outperforms per-row digests in-memory and is
  exact; SHA-256 row hashing (Module 32) is reserved for the Enterprise
  Edition's cross-database pushdown comparison where rows never co-reside.
- Null semantics, float tolerance (np.isclose, boundary-safe), string
  trimming, and case folding are all configurable and vectorized.
- The cell-level mismatch diff is computed only on the (typically small)
  mismatch subset, chunked as a memory guard.
- Scales to the 5M-record Community Edition target on a single node.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

logger = logging.getLogger("datarecon.core.engine.comparison")

__all__ = [
    "ComparisonConfig",
    "ComparisonEngine",
    "ComparisonEngineError",
    "ComparisonResult",
    "DuplicateBusinessKeyError",
    "SchemaAlignmentError",
]


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #
class ComparisonEngineError(Exception):
    """Base exception for the comparison engine."""


class DuplicateBusinessKeyError(ComparisonEngineError):
    """Raised when business keys are not unique in source or target."""

    def __init__(self, side: str, duplicate_count: int) -> None:
        self.side = side
        self.duplicate_count = duplicate_count
        super().__init__(
            f"{duplicate_count} duplicate business-key rows found in {side}. "
            f"Key-based comparison requires unique keys; resolve duplicates "
            f"via Module 4 (Duplicate Validation) or enable "
            f"ComparisonConfig(drop_duplicate_keys=True)."
        )


class SchemaAlignmentError(ComparisonEngineError):
    """Raised when the business keys or comparison columns cannot be aligned."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ComparisonConfig:
    """Tunable behavior for a comparison run."""

    #: Columns to compare. None = intersection of non-key columns.
    compare_columns: Sequence[str] | None = None
    #: Treat NULL == NULL as equal (recommended for reconciliation).
    nulls_equal: bool = True
    #: Trim leading/trailing whitespace on string columns before comparing.
    trim_strings: bool = False
    #: Case-insensitive string comparison.
    ignore_case: bool = False
    #: Absolute tolerance for float comparison (0.0 = exact).
    float_tolerance: float = 0.0
    #: Drop duplicate-key rows (keep first) instead of raising.
    drop_duplicate_keys: bool = False
    #: Match column and business-key *names* case-insensitively, so a source
    #: CUSTOMER_ID lines up with a target customer_id. Source spelling wins as
    #: the canonical name in the output. This is about identifying columns, not
    #: comparing their values — `ignore_case` governs the values.
    case_insensitive_columns: bool = True
    #: Chunk size for the cell-level mismatch diff (memory guard, Module 32).
    diff_chunk_size: int = 500_000


# --------------------------------------------------------------------------- #
# Result value object
# --------------------------------------------------------------------------- #
@dataclass
class ComparisonResult:
    """Outcome of one Source-vs-Target comparison run (Module 6 outputs)."""

    exact_match: pd.DataFrame
    mismatch: pd.DataFrame
    missing_in_target: pd.DataFrame  # present in Source, absent in Target
    extra_in_target: pd.DataFrame  # present in Target, absent in Source
    summary: dict = field(default_factory=dict)

    def is_passed(self) -> bool:
        return self.summary.get("success_percentage", 0.0) == 100.0


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class ComparisonEngine:
    """
    Key-based Source-vs-Target full data validation (PRD Module 6).

    Usage
    -----
    >>> engine = ComparisonEngine(business_keys=["CUST_ID"])
    >>> result = engine.compare(source_df, target_df)
    >>> result.summary["success_percentage"]
    """

    _MERGE_INDICATOR = "_dr_merge_"
    _SRC_SUFFIX = "_source"
    _TGT_SUFFIX = "_target"

    def __init__(
        self,
        business_keys: Sequence[str],
        config: ComparisonConfig | None = None,
    ) -> None:
        if not business_keys:
            raise SchemaAlignmentError("At least one business key is required.")
        self.business_keys: list[str] = list(business_keys)
        self.config = config or ComparisonConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def compare(self, source: pd.DataFrame, target: pd.DataFrame) -> ComparisonResult:
        """Execute the full comparison and return a ComparisonResult."""
        source, target = self._align_column_case(source, target)
        src = self._prepare(source, side="source")
        tgt = self._prepare(target, side="target")

        compare_cols = self._resolve_compare_columns(src, tgt)
        logger.info(
            "Comparing %d source rows vs %d target rows on keys=%s, columns=%d",
            len(src),
            len(tgt),
            self.business_keys,
            len(compare_cols),
        )

        # ---- Set split via indicator merge (vectorized) ----
        merged = src.merge(
            tgt,
            on=self.business_keys,
            how="outer",
            suffixes=(self._SRC_SUFFIX, self._TGT_SUFFIX),
            indicator=self._MERGE_INDICATOR,
        )
        ind = merged[self._MERGE_INDICATOR]

        missing_in_target = self._project_side(
            merged.loc[ind == "left_only"], compare_cols, self._SRC_SUFFIX
        )
        extra_in_target = self._project_side(
            merged.loc[ind == "right_only"], compare_cols, self._TGT_SUFFIX
        )

        both = merged.loc[ind == "both"]

        # ---- Match / mismatch split: column-wise vectorized equality ----
        if compare_cols and len(both) > 0:
            equal_mask = np.ones(len(both), dtype=bool)
            for col in compare_cols:
                s = both[self._suffixed(both, col, self._SRC_SUFFIX)]
                t = both[self._suffixed(both, col, self._TGT_SUFFIX)]
                equal_mask &= self._column_equal(s, t)
        else:
            # Key-only comparison: presence in both sides == exact match.
            equal_mask = np.ones(len(both), dtype=bool)

        exact_match = self._project_side(both.loc[equal_mask], compare_cols, self._SRC_SUFFIX)
        mismatch = self._build_mismatch_frame(both.loc[~equal_mask], compare_cols)

        summary = self._build_summary(
            rows_source=len(src),
            rows_target=len(tgt),
            matched=len(exact_match),
            mismatched=int((~equal_mask).sum()),
            missing=len(missing_in_target),
            extra=len(extra_in_target),
        )

        return ComparisonResult(
            exact_match=exact_match.reset_index(drop=True),
            mismatch=mismatch.reset_index(drop=True),
            missing_in_target=missing_in_target.reset_index(drop=True),
            extra_in_target=extra_in_target.reset_index(drop=True),
            summary=summary,
        )

    # ------------------------------------------------------------------ #
    # Preparation & validation
    # ------------------------------------------------------------------ #
    def _align_column_case(
        self, source: pd.DataFrame, target: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Reconcile column names that differ only by case.

        Databases disagree on identifier casing (Oracle upper-cases, Postgres
        lower-cases, others preserve), so the same logical column arrives as
        CUSTOMER_ID on one side and customer_id on the other. Source spelling
        is canonical: target columns are renamed to it, and the configured
        business keys / compare columns are resolved against it too, so a key
        typed in either case still matches.
        """
        if not self.config.case_insensitive_columns or source is None or target is None:
            return source, target

        canonical = {str(c).casefold(): str(c) for c in source.columns}
        renames = {
            c: canonical[str(c).casefold()]
            for c in target.columns
            if str(c).casefold() in canonical and str(c) != canonical[str(c).casefold()]
        }
        if renames:
            target = target.rename(columns=renames)

        self.business_keys = [canonical.get(str(k).casefold(), k) for k in self.business_keys]
        if self.config.compare_columns is not None:
            self.config = replace(
                self.config,
                compare_columns=[
                    canonical.get(str(c).casefold(), c) for c in self.config.compare_columns
                ],
            )
        return source, target

    def _prepare(self, df: pd.DataFrame, side: str) -> pd.DataFrame:
        if df is None:
            raise SchemaAlignmentError(f"{side} DataFrame is None.")
        missing_keys = [k for k in self.business_keys if k not in df.columns]
        if missing_keys:
            raise SchemaAlignmentError(
                f"Business key(s) {missing_keys} not found in {side} columns."
            )

        out = df.copy(deep=False)

        # Normalize string columns if configured (vectorized .str ops).
        if self.config.trim_strings or self.config.ignore_case:
            obj_cols = out.select_dtypes(include=["object", "string"]).columns
            for col in obj_cols:
                s = out[col]
                if self.config.trim_strings:
                    s = s.str.strip()
                if self.config.ignore_case:
                    s = s.str.upper()
                out[col] = s

        # Enforce key uniqueness (Module 6 key-based contract).
        dup_mask = out.duplicated(subset=self.business_keys, keep="first")
        dup_count = int(dup_mask.sum())
        if dup_count:
            if self.config.drop_duplicate_keys:
                logger.warning("Dropping %d duplicate-key rows from %s.", dup_count, side)
                out = out.loc[~dup_mask]
            else:
                raise DuplicateBusinessKeyError(side, dup_count)

        return out

    def _resolve_compare_columns(self, src: pd.DataFrame, tgt: pd.DataFrame) -> list[str]:
        keys = set(self.business_keys)
        if self.config.compare_columns is not None:
            cols = [c for c in self.config.compare_columns if c not in keys]
            missing_src = [c for c in cols if c not in src.columns]
            missing_tgt = [c for c in cols if c not in tgt.columns]
            if missing_src or missing_tgt:
                raise SchemaAlignmentError(
                    f"Configured compare columns missing — "
                    f"source: {missing_src}, target: {missing_tgt}"
                )
            return cols
        # Default: ordered intersection of non-key columns (source order).
        tgt_cols = set(tgt.columns)
        return [c for c in src.columns if c in tgt_cols and c not in keys]

    # ------------------------------------------------------------------ #
    # Vectorized column equality (single source of truth for semantics)
    # ------------------------------------------------------------------ #
    def _column_equal(self, s: pd.Series, t: pd.Series) -> np.ndarray:
        """
        Boolean ndarray: element-wise equality between aligned source/target
        columns, honoring nulls_equal and float_tolerance. Fully vectorized.
        """
        cfg = self.config
        s_na = s.isna().to_numpy()
        t_na = t.isna().to_numpy()
        both_na = s_na & t_na

        s_is_num = pd.api.types.is_numeric_dtype(s)
        t_is_num = pd.api.types.is_numeric_dtype(t)
        s_is_float = pd.api.types.is_float_dtype(s)
        t_is_float = pd.api.types.is_float_dtype(t)

        if (s_is_float or t_is_float) and s_is_num and t_is_num:
            a = s.astype("float64").to_numpy(na_value=np.nan)
            b = t.astype("float64").to_numpy(na_value=np.nan)
            if cfg.float_tolerance > 0:
                # Boundary-safe: |a - b| <= atol (no quantization buckets).
                eq = np.isclose(a, b, rtol=0.0, atol=cfg.float_tolerance, equal_nan=False)
            else:
                with np.errstate(invalid="ignore"):
                    eq = a == b
        else:
            # pandas .eq handles mixed nullable dtypes; NA-involved
            # comparisons yield NA -> treated as not-equal here.
            eq_series = s.eq(t)
            if eq_series.isna().any():
                eq_series = eq_series.fillna(False)
            eq = eq_series.to_numpy(dtype=bool)

        # Null semantics applied uniformly across all dtype paths.
        # Note: no in-place ops — pandas 3.x .to_numpy() may return
        # read-only views.
        eq = eq & ~(s_na | t_na)  # any NA involvement -> not equal ...
        if cfg.nulls_equal:
            eq = eq | both_na  # ... unless both NA and NULL==NULL.
        return eq

    # ------------------------------------------------------------------ #
    # Output construction
    # ------------------------------------------------------------------ #
    def _suffixed(self, merged: pd.DataFrame, col: str, suffix: str) -> str:
        """Resolve the merged column name for one side (handles no-collision case)."""
        cand = f"{col}{suffix}"
        if cand in merged.columns:
            return cand
        if col in merged.columns:
            return col  # column existed on only one side pre-merge
        raise SchemaAlignmentError(f"Column '{col}' lost during merge alignment.")

    def _project_side(
        self, merged_slice: pd.DataFrame, compare_cols: list[str], suffix: str
    ) -> pd.DataFrame:
        """Rebuild a clean single-side frame (keys + compare cols) from merged rows."""
        if merged_slice.empty:
            return pd.DataFrame(columns=self.business_keys + compare_cols)
        data = {k: merged_slice[k] for k in self.business_keys}
        for c in compare_cols:
            data[c] = merged_slice[self._suffixed(merged_slice, c, suffix)]
        return pd.DataFrame(data)

    def _build_mismatch_frame(
        self, mismatch_rows: pd.DataFrame, compare_cols: list[str]
    ) -> pd.DataFrame:
        """
        Wide diff frame: business keys + <col>_source / <col>_target pairs +
        MISMATCHED_COLUMNS listing the differing columns per row.
        Computed only on the mismatch subset, in chunks (Module 32 memory guard).
        """
        diff_cols = [f"{c}{s}" for c in compare_cols for s in (self._SRC_SUFFIX, self._TGT_SUFFIX)]
        if mismatch_rows.empty or not compare_cols:
            return pd.DataFrame(columns=self.business_keys + diff_cols + ["MISMATCHED_COLUMNS"])

        chunks: list[pd.DataFrame] = []
        n = len(mismatch_rows)
        step = max(self.config.diff_chunk_size, 1)
        col_arr = np.array(compare_cols, dtype=object)

        for start in range(0, n, step):
            block = mismatch_rows.iloc[start : start + step]
            out = pd.DataFrame({k: block[k].to_numpy() for k in self.business_keys})

            diff_flags = np.zeros((len(block), len(compare_cols)), dtype=bool)
            for j, c in enumerate(compare_cols):
                s_col = self._suffixed(block, c, self._SRC_SUFFIX)
                t_col = self._suffixed(block, c, self._TGT_SUFFIX)
                diff_flags[:, j] = ~self._column_equal(block[s_col], block[t_col])
                out[f"{c}{self._SRC_SUFFIX}"] = block[s_col].to_numpy()
                out[f"{c}{self._TGT_SUFFIX}"] = block[t_col].to_numpy()

            out["MISMATCHED_COLUMNS"] = [",".join(col_arr[row]) for row in diff_flags]
            chunks.append(out)

        return pd.concat(chunks, ignore_index=True)

    # ------------------------------------------------------------------ #
    # Summary (Module 6 outputs)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_summary(
        rows_source: int,
        rows_target: int,
        matched: int,
        mismatched: int,
        missing: int,
        extra: int,
    ) -> dict:
        rows_compared = matched + mismatched + missing + extra
        success_pct = round((matched / rows_compared) * 100.0, 4) if rows_compared else 100.0
        return {
            "rows_source": rows_source,
            "rows_target": rows_target,
            "rows_compared": rows_compared,
            "rows_matched": matched,
            "rows_mismatched": mismatched,
            "rows_missing_in_target": missing,
            "rows_extra_in_target": extra,
            "rows_failed": mismatched + missing + extra,
            "success_percentage": success_pct,
            "status": "PASS" if success_pct == 100.0 else "FAIL",
        }
