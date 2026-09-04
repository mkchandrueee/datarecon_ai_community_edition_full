"""Unit tests — RunDetailStore (Parquet-backed row-level detail persistence)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from datarecon.infrastructure.persistence.run_detail_store import RunDetailStore


@pytest.fixture
def store(tmp_path: Path) -> RunDetailStore:
    return RunDetailStore(tmp_path / "run_details")


def test_save_then_load_all_round_trips_every_section(store: RunDetailStore) -> None:
    details = {
        "Mismatches": pd.DataFrame({"id": [1, 2], "value_source": [1, 2], "value_target": [9, 2]}),
        "Missing in Target": pd.DataFrame({"id": [3]}),
    }
    store.save("run-1", details)

    loaded = store.load_all("run-1")
    assert set(loaded.keys()) == {"Mismatches", "Missing in Target"}
    pd.testing.assert_frame_equal(loaded["Mismatches"], details["Mismatches"])
    pd.testing.assert_frame_equal(loaded["Missing in Target"], details["Missing in Target"])


def test_list_sections_returns_saved_titles_in_order(store: RunDetailStore) -> None:
    store.save(
        "run-1",
        {
            "Column Profiles": pd.DataFrame({"column": ["a"]}),
            "Top Values - a": pd.DataFrame({"value": ["x"], "frequency": [1]}),
        },
    )
    assert store.list_sections("run-1") == ["Column Profiles", "Top Values - a"]


def test_load_single_section_by_title(store: RunDetailStore) -> None:
    df = pd.DataFrame({"column": ["id", "name"], "status": ["MATCH", "MATCH"]})
    store.save("run-1", {"Column Comparison": df})

    loaded = store.load("run-1", "Column Comparison")
    assert loaded is not None
    pd.testing.assert_frame_equal(loaded, df)


def test_load_unknown_section_returns_none(store: RunDetailStore) -> None:
    store.save("run-1", {"Column Comparison": pd.DataFrame({"a": [1]})})
    assert store.load("run-1", "Does Not Exist") is None


def test_unknown_run_has_no_sections(store: RunDetailStore) -> None:
    assert store.list_sections("ghost-run") == []
    assert store.load_all("ghost-run") == {}
    assert store.load("ghost-run", "anything") is None
    assert store.has_detail("ghost-run") is False


def test_has_detail_true_only_after_save(store: RunDetailStore) -> None:
    assert store.has_detail("run-1") is False
    store.save("run-1", {"Column Comparison": pd.DataFrame({"a": [1]})})
    assert store.has_detail("run-1") is True


def test_save_with_empty_details_is_a_noop(store: RunDetailStore, tmp_path: Path) -> None:
    store.save("run-1", {})
    assert store.list_sections("run-1") == []
    assert not (tmp_path / "run_details" / "run-1").exists()


def test_save_persists_to_a_parquet_file_per_section(store: RunDetailStore, tmp_path: Path) -> None:
    store.save("run-1", {"Mismatches": pd.DataFrame({"a": [1]})})
    run_dir = tmp_path / "run_details" / "run-1"
    parquet_files = list(run_dir.glob("*.parquet"))
    assert len(parquet_files) == 1
    assert parquet_files[0].suffix == ".parquet"


def test_titles_with_special_characters_are_slugified_and_still_retrievable(
    store: RunDetailStore,
) -> None:
    title = "Top Values - customer_id/notes"
    df = pd.DataFrame({"value": [1], "frequency": [5]})
    store.save("run-1", {title: df})

    assert store.list_sections("run-1") == [title]
    loaded = store.load("run-1", title)
    assert loaded is not None
    pd.testing.assert_frame_equal(loaded, df)


def test_colliding_slugs_get_unique_filenames(store: RunDetailStore) -> None:
    details = {
        "a/b": pd.DataFrame({"x": [1]}),
        "a-b": pd.DataFrame({"x": [2]}),
    }
    store.save("run-1", details)

    loaded = store.load_all("run-1")
    assert set(loaded.keys()) == {"a/b", "a-b"}
    assert loaded["a/b"]["x"].iloc[0] == 1
    assert loaded["a-b"]["x"].iloc[0] == 2


def test_runs_are_isolated_from_each_other(store: RunDetailStore) -> None:
    store.save("run-1", {"Mismatches": pd.DataFrame({"a": [1]})})
    store.save("run-2", {"Mismatches": pd.DataFrame({"a": [2]})})

    assert store.load("run-1", "Mismatches")["a"].iloc[0] == 1
    assert store.load("run-2", "Mismatches")["a"].iloc[0] == 2


# ---------- deletion (ADR-0016) ----------


def test_delete_removes_every_section_for_a_run(tmp_path) -> None:
    store = RunDetailStore(tmp_path / "details")
    store.save("run-1", {"Mismatches": pd.DataFrame({"a": [1]}), "Matched": pd.DataFrame({"a": [2]})})

    assert store.delete("run-1") is True
    assert store.has_detail("run-1") is False
    assert store.load_all("run-1") == {}


def test_delete_leaves_other_runs_alone(tmp_path) -> None:
    store = RunDetailStore(tmp_path / "details")
    store.save("run-1", {"Mismatches": pd.DataFrame({"a": [1]})})
    store.save("run-2", {"Mismatches": pd.DataFrame({"a": [2]})})

    store.delete("run-1")

    assert store.has_detail("run-2") is True


def test_delete_reports_false_when_there_was_nothing_stored(tmp_path) -> None:
    assert RunDetailStore(tmp_path / "details").delete("never-ran") is False
