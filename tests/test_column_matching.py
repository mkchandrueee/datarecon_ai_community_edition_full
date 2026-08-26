"""Unit tests — case-insensitive column-name matching (ADR-0009)."""

from __future__ import annotations

import pandas as pd

from datarecon.core.column_matching import align_to_source, canonical_map, resolve, resolve_all


def test_canonical_map_folds_case() -> None:
    assert canonical_map(["CUSTOMER_ID", "Email"]) == {
        "customer_id": "CUSTOMER_ID",
        "email": "Email",
    }


def test_canonical_map_first_spelling_wins_on_collision() -> None:
    assert canonical_map(["ID", "id"]) == {"id": "ID"}


def test_resolve_finds_actual_spelling() -> None:
    assert resolve("customer_id", ["CUSTOMER_ID", "EMAIL"]) == "CUSTOMER_ID"
    assert resolve("CUSTOMER_ID", ["customer_id"]) == "customer_id"


def test_resolve_returns_none_when_absent() -> None:
    assert resolve("missing", ["A", "B"]) is None


def test_resolve_all_splits_found_and_missing() -> None:
    resolved, missing = resolve_all(["id", "nope"], ["ID", "EMAIL"])
    assert resolved == ["ID"]
    assert missing == ["nope"]


def test_resolve_all_reports_missing_as_typed() -> None:
    _, missing = resolve_all(["NoSuchColumn"], ["A"])
    assert missing == ["NoSuchColumn"]


def test_align_to_source_renames_case_only_differences() -> None:
    source = pd.DataFrame({"CUSTOMER_ID": [1], "EMAIL": ["a"]})
    target = pd.DataFrame({"customer_id": [1], "email": ["a"]})

    aligned = align_to_source(source, target)

    assert list(aligned.columns) == ["CUSTOMER_ID", "EMAIL"]


def test_align_to_source_leaves_genuinely_extra_columns_alone() -> None:
    source = pd.DataFrame({"ID": [1]})
    target = pd.DataFrame({"id": [1], "EXTRA": ["x"]})

    aligned = align_to_source(source, target)

    assert list(aligned.columns) == ["ID", "EXTRA"]


def test_align_to_source_is_a_noop_when_names_already_match() -> None:
    source = pd.DataFrame({"ID": [1]})
    target = pd.DataFrame({"ID": [2]})

    assert align_to_source(source, target) is target
