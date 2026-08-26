"""Unit tests — DataRecon AI ComparisonEngine (Module 6 / Module 32)."""

import numpy as np
import pandas as pd
import pytest

from datarecon.core.engine import (
    ComparisonConfig,
    ComparisonEngine,
    DuplicateBusinessKeyError,
    SchemaAlignmentError,
)


@pytest.fixture
def source_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CUST_ID": [1, 2, 3, 4],
            "NAME": ["Alice", "Bob", "Carol", "Dave"],
            "BALANCE": [100.0, 200.0, 300.0, 400.0],
        }
    )


@pytest.fixture
def target_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CUST_ID": [1, 2, 3, 5],
            "NAME": ["Alice", "Bobby", "Carol", "Eve"],
            "BALANCE": [100.0, 200.0, 300.0, 500.0],
        }
    )


class TestFourWaySplit:
    def test_categories(self, source_df, target_df):
        result = ComparisonEngine(["CUST_ID"]).compare(source_df, target_df)
        assert sorted(result.exact_match["CUST_ID"].tolist()) == [1, 3]
        assert result.mismatch["CUST_ID"].tolist() == [2]
        assert result.missing_in_target["CUST_ID"].tolist() == [4]
        assert result.extra_in_target["CUST_ID"].tolist() == [5]

    def test_mismatch_diff_columns(self, source_df, target_df):
        result = ComparisonEngine(["CUST_ID"]).compare(source_df, target_df)
        row = result.mismatch.iloc[0]
        assert row["NAME_source"] == "Bob"
        assert row["NAME_target"] == "Bobby"
        assert row["MISMATCHED_COLUMNS"] == "NAME"

    def test_multi_column_mismatch_listing(self):
        src = pd.DataFrame({"K": [1], "A": [1], "B": ["x"]})
        tgt = pd.DataFrame({"K": [1], "A": [2], "B": ["y"]})
        result = ComparisonEngine(["K"]).compare(src, tgt)
        assert result.mismatch.iloc[0]["MISMATCHED_COLUMNS"] == "A,B"

    def test_summary_math(self, source_df, target_df):
        s = ComparisonEngine(["CUST_ID"]).compare(source_df, target_df).summary
        assert s["rows_compared"] == 5
        assert s["rows_matched"] == 2
        assert s["rows_mismatched"] == 1
        assert s["rows_missing_in_target"] == 1
        assert s["rows_extra_in_target"] == 1
        assert s["rows_failed"] == 3
        assert s["success_percentage"] == 40.0
        assert s["status"] == "FAIL"

    def test_perfect_match(self, source_df):
        r = ComparisonEngine(["CUST_ID"]).compare(source_df, source_df.copy())
        assert r.summary["success_percentage"] == 100.0
        assert r.summary["status"] == "PASS"
        assert r.is_passed()


class TestCompositeKeys:
    def test_composite_key(self):
        src = pd.DataFrame({"K1": [1, 1, 2], "K2": ["A", "B", "A"], "V": [10, 20, 30]})
        tgt = pd.DataFrame({"K1": [1, 1, 2], "K2": ["A", "B", "A"], "V": [10, 99, 30]})
        result = ComparisonEngine(["K1", "K2"]).compare(src, tgt)
        assert len(result.exact_match) == 2
        assert len(result.mismatch) == 1
        assert result.mismatch.iloc[0]["V_source"] == 20
        assert result.mismatch.iloc[0]["V_target"] == 99


class TestNullAndTypeSemantics:
    def test_nulls_equal_default(self):
        src = pd.DataFrame({"K": [1], "V": [np.nan]})
        tgt = pd.DataFrame({"K": [1], "V": [np.nan]})
        assert len(ComparisonEngine(["K"]).compare(src, tgt).exact_match) == 1

    def test_nulls_not_equal(self):
        src = pd.DataFrame({"K": [1], "V": [np.nan]})
        tgt = pd.DataFrame({"K": [1], "V": [np.nan]})
        cfg = ComparisonConfig(nulls_equal=False)
        assert len(ComparisonEngine(["K"], cfg).compare(src, tgt).mismatch) == 1

    def test_null_vs_value_is_mismatch(self):
        src = pd.DataFrame({"K": [1], "V": [np.nan]})
        tgt = pd.DataFrame({"K": [1], "V": [5.0]})
        assert len(ComparisonEngine(["K"]).compare(src, tgt).mismatch) == 1

    def test_float_tolerance_boundary_safe(self):
        src = pd.DataFrame({"K": [1, 2], "V": [100.004, 50.0]})
        tgt = pd.DataFrame({"K": [1, 2], "V": [100.006, 50.5]})
        cfg = ComparisonConfig(float_tolerance=0.01)
        result = ComparisonEngine(["K"], cfg).compare(src, tgt)
        assert len(result.exact_match) == 1
        assert len(result.mismatch) == 1

    def test_int_vs_float_numeric_equality(self):
        src = pd.DataFrame({"K": [1], "V": pd.array([100], dtype="Int64")})
        tgt = pd.DataFrame({"K": [1], "V": [100.0]})
        assert len(ComparisonEngine(["K"]).compare(src, tgt).exact_match) == 1

    def test_trim_and_case(self):
        src = pd.DataFrame({"K": [1], "V": ["  alice "]})
        tgt = pd.DataFrame({"K": [1], "V": ["ALICE"]})
        cfg = ComparisonConfig(trim_strings=True, ignore_case=True)
        assert len(ComparisonEngine(["K"], cfg).compare(src, tgt).exact_match) == 1

    def test_datetime_columns(self):
        src = pd.DataFrame({"K": [1, 2], "V": pd.to_datetime(["2026-01-01", "2026-01-02"])})
        tgt = pd.DataFrame({"K": [1, 2], "V": pd.to_datetime(["2026-01-01", "2026-06-30"])})
        result = ComparisonEngine(["K"]).compare(src, tgt)
        assert len(result.exact_match) == 1
        assert len(result.mismatch) == 1


class TestConfiguration:
    def test_compare_columns_subset(self):
        src = pd.DataFrame({"K": [1], "V": [1], "IGNORED": [9]})
        tgt = pd.DataFrame({"K": [1], "V": [1], "IGNORED": [7]})
        cfg = ComparisonConfig(compare_columns=["V"])
        assert len(ComparisonEngine(["K"], cfg).compare(src, tgt).exact_match) == 1


class TestGuards:
    def test_duplicate_keys_raise(self):
        src = pd.DataFrame({"K": [1, 1], "V": [1, 2]})
        tgt = pd.DataFrame({"K": [1], "V": [1]})
        with pytest.raises(DuplicateBusinessKeyError):
            ComparisonEngine(["K"]).compare(src, tgt)

    def test_duplicate_keys_dropped_when_configured(self):
        src = pd.DataFrame({"K": [1, 1], "V": [1, 2]})
        tgt = pd.DataFrame({"K": [1], "V": [1]})
        cfg = ComparisonConfig(drop_duplicate_keys=True)
        s = ComparisonEngine(["K"], cfg).compare(src, tgt).summary
        assert s["rows_compared"] == 1
        assert s["status"] == "PASS"

    def test_missing_key_column(self):
        with pytest.raises(SchemaAlignmentError):
            ComparisonEngine(["K"]).compare(pd.DataFrame({"K": [1]}), pd.DataFrame({"X": [1]}))

    def test_empty_key_list(self):
        with pytest.raises(SchemaAlignmentError):
            ComparisonEngine([])

    def test_empty_frames(self):
        empty = pd.DataFrame({"K": [], "V": []})
        s = ComparisonEngine(["K"]).compare(empty, empty).summary
        assert s["rows_compared"] == 0
        assert s["success_percentage"] == 100.0


class TestScale:
    def test_200k_vectorized_run(self):
        n = 200_000
        keys = np.arange(n)
        src = pd.DataFrame({"K": keys, "V": keys * 2, "S": "x"})
        tgt = src.copy()
        tgt.loc[tgt.index[:100], "V"] = -1  # 100 value changes
        tgt = tgt.iloc[50:]  # first 50 rows removed
        extra = pd.DataFrame({"K": np.arange(n, n + 25), "V": 0, "S": "x"})
        tgt = pd.concat([tgt, extra], ignore_index=True)

        s = ComparisonEngine(["K"]).compare(src, tgt).summary
        assert s["rows_missing_in_target"] == 50
        assert s["rows_extra_in_target"] == 25
        assert s["rows_mismatched"] == 50  # 50 changed rows survive the slice
        assert s["rows_matched"] == n - 100
        assert s["rows_compared"] == s["rows_matched"] + s["rows_failed"]

    @pytest.mark.slow
    def test_5m_prd_target(self):
        n = 5_000_000
        keys = np.arange(n)
        src = pd.DataFrame(
            {"K": keys, "AMT": np.random.rand(n), "QTY": np.random.randint(0, 100, n)}
        )
        tgt = src.copy()
        tgt.loc[tgt.index[:1000], "AMT"] += 1.0
        s = ComparisonEngine(["K"]).compare(src, tgt).summary
        assert s["rows_mismatched"] == 1000
        assert s["rows_matched"] == n - 1000


class TestCaseInsensitiveColumnNames:
    """Databases disagree on identifier casing, so the same logical column can
    arrive as CUSTOMER_ID on one side and customer_id on the other."""

    def test_target_columns_differing_only_by_case_are_matched(self):
        src = pd.DataFrame({"CUSTOMER_ID": [1, 2], "EMAIL": ["a@x", "b@x"]})
        tgt = pd.DataFrame({"customer_id": [1, 2], "email": ["a@x", "b@x"]})

        result = ComparisonEngine(["CUSTOMER_ID"]).compare(src, tgt)

        assert result.summary["rows_matched"] == 2
        assert result.summary["rows_missing_in_target"] == 0
        assert result.summary["rows_extra_in_target"] == 0

    def test_business_key_typed_in_other_case_still_resolves(self):
        src = pd.DataFrame({"CUSTOMER_ID": [1, 2], "EMAIL": ["a@x", "b@x"]})
        tgt = pd.DataFrame({"CUSTOMER_ID": [1, 2], "EMAIL": ["a@x", "b@x"]})

        result = ComparisonEngine(["customer_id"]).compare(src, tgt)

        assert result.summary["rows_matched"] == 2

    def test_source_spelling_is_canonical_in_output(self):
        src = pd.DataFrame({"CUSTOMER_ID": [1], "EMAIL": ["a@x"]})
        tgt = pd.DataFrame({"customer_id": [1], "email": ["b@x"]})

        result = ComparisonEngine(["CUSTOMER_ID"]).compare(src, tgt)

        assert result.summary["rows_mismatched"] == 1
        assert "EMAIL" in result.mismatch["MISMATCHED_COLUMNS"].iloc[0]

    def test_mismatched_values_still_detected_across_casing(self):
        src = pd.DataFrame({"ID": [1, 2], "AMT": [10, 20]})
        tgt = pd.DataFrame({"id": [1, 2], "amt": [10, 99]})

        result = ComparisonEngine(["ID"]).compare(src, tgt)

        assert result.summary["rows_matched"] == 1
        assert result.summary["rows_mismatched"] == 1

    def test_compare_columns_resolve_case_insensitively(self):
        src = pd.DataFrame({"ID": [1], "AMT": [10], "NOTE": ["x"]})
        tgt = pd.DataFrame({"id": [1], "amt": [99], "note": ["y"]})

        config = ComparisonConfig(compare_columns=["amt"])
        result = ComparisonEngine(["ID"], config).compare(src, tgt)

        assert result.summary["rows_mismatched"] == 1
        assert "AMT" in result.mismatch["MISMATCHED_COLUMNS"].iloc[0]
        assert "NOTE" not in result.mismatch["MISMATCHED_COLUMNS"].iloc[0]

    def test_can_be_disabled(self):
        src = pd.DataFrame({"CUSTOMER_ID": [1]})
        tgt = pd.DataFrame({"customer_id": [1]})

        config = ComparisonConfig(case_insensitive_columns=False)
        with pytest.raises(SchemaAlignmentError, match="not found in target"):
            ComparisonEngine(["CUSTOMER_ID"], config).compare(src, tgt)
