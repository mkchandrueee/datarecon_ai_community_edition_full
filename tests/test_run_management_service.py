"""Unit tests — RunManagementService (bulk extract / archive / delete, ADR-0016)."""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from io import BytesIO

import pandas as pd
import pytest

from datarecon.application.services.reporting_service import ReportingService
from datarecon.application.services.run_management_service import RunManagementService
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import RunStatus, ValidationModule


@pytest.fixture
def service(run_repository, detail_store) -> RunManagementService:
    return RunManagementService(run_repository, detail_store, ReportingService())


def _add_run(
    run_repository,
    detail_store,
    name: str = "CUSTOMER_MASTER",
    module: ValidationModule = ValidationModule.FULL_DATA,
    sections: dict[str, pd.DataFrame] | None = None,
) -> ValidationRun:
    run = run_repository.add(
        ValidationRun(
            module=module,
            name=name,
            status=RunStatus.FAIL,
            summary={"rows_compared": 100, "rows_mismatched": 7},
            started_at=datetime(2026, 3, 5, 6, 30, tzinfo=UTC),
            finished_at=datetime(2026, 3, 5, 6, 31, tzinfo=UTC),
        )
    )
    if sections:
        detail_store.save(run.run_id, sections)
    return run


def _zip_names(payload: bytes) -> list[str]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return sorted(archive.namelist())


def _zip_text(payload: bytes, name: str) -> str:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return archive.read(name).decode("utf-8")


# ---------- archive ----------


def test_archive_hides_every_selected_run(service, run_repository, detail_store) -> None:
    a = _add_run(run_repository, detail_store, name="A")
    b = _add_run(run_repository, detail_store, name="B")

    result = service.archive_runs([a.run_id, b.run_id])

    assert result.succeeded == 2
    assert run_repository.list_filtered(include_archived=False) == []


def test_restore_brings_runs_back(service, run_repository, detail_store) -> None:
    run = _add_run(run_repository, detail_store)
    service.archive_runs([run.run_id])

    service.archive_runs([run.run_id], archived=False)

    assert [r.run_id for r in run_repository.list_filtered()] == [run.run_id]


def test_archiving_leaves_the_row_level_detail_intact(
    service, run_repository, detail_store
) -> None:
    """Archive is the reversible option — it must not destroy anything."""
    run = _add_run(
        run_repository, detail_store, sections={"Mismatches": pd.DataFrame({"a": [1, 2]})}
    )

    service.archive_runs([run.run_id])

    assert detail_store.has_detail(run.run_id)


def test_an_unknown_run_id_is_reported_rather_than_counted(service) -> None:
    result = service.archive_runs(["nope"])

    assert result.succeeded == 0
    assert result.missing == ["nope"]
    assert result.failed == 1


# ---------- delete ----------


def test_delete_removes_the_run_and_its_detail(service, run_repository, detail_store) -> None:
    run = _add_run(
        run_repository, detail_store, sections={"Mismatches": pd.DataFrame({"a": [1, 2]})}
    )

    result = service.delete_runs([run.run_id])

    assert result.succeeded == 1
    assert run_repository.get_by_id(run.run_id) is None
    assert not detail_store.has_detail(run.run_id)


def test_delete_leaves_the_runs_that_were_not_selected(
    service, run_repository, detail_store
) -> None:
    keep = _add_run(run_repository, detail_store, name="KEEP")
    drop = _add_run(run_repository, detail_store, name="DROP")

    service.delete_runs([drop.run_id])

    assert [r.run_id for r in run_repository.list_filtered()] == [keep.run_id]


def test_deleting_a_run_without_detail_still_succeeds(
    service, run_repository, detail_store
) -> None:
    run = _add_run(run_repository, detail_store)

    assert service.delete_runs([run.run_id]).succeeded == 1


def test_deleting_an_unknown_run_reports_it(service) -> None:
    result = service.delete_runs(["nope"])

    assert result.succeeded == 0
    assert result.missing == ["nope"]


def test_deleting_the_same_run_twice_is_not_counted_twice(
    service, run_repository, detail_store
) -> None:
    run = _add_run(run_repository, detail_store)
    service.delete_runs([run.run_id])

    assert service.delete_runs([run.run_id]).succeeded == 0


# ---------- extract ----------


def test_the_export_holds_one_folder_per_run(service, run_repository, detail_store) -> None:
    a = _add_run(
        run_repository, detail_store, name="ORDERS",
        sections={"Mismatches": pd.DataFrame({"a": [1]})},
    )
    b = _add_run(
        run_repository, detail_store, name="CUSTOMERS",
        sections={"Mismatches": pd.DataFrame({"a": [2]})},
    )

    names = _zip_names(service.build_export([a.run_id, b.run_id]))

    assert "FD_ORDERS/summary.csv" in names
    assert "FD_CUSTOMERS/summary.csv" in names
    assert "FD_ORDERS/Mismatches.csv" in names


def test_the_export_carries_a_manifest_naming_each_folder(
    service, run_repository, detail_store
) -> None:
    """A folder of folders is only navigable if something says what they are."""
    run = _add_run(run_repository, detail_store, name="ORDERS")

    manifest = _zip_text(service.build_export([run.run_id]), "manifest.csv")

    assert "FD_ORDERS" in manifest
    assert run.run_id in manifest
    assert "FAIL" in manifest


def test_the_summary_csv_holds_the_run_metrics(service, run_repository, detail_store) -> None:
    run = _add_run(run_repository, detail_store, name="ORDERS")

    summary = _zip_text(service.build_export([run.run_id]), "FD_ORDERS/summary.csv")

    assert "rows_mismatched" in summary and "7" in summary


def test_oversized_sections_are_split_inside_the_zip(
    service, run_repository, detail_store
) -> None:
    """A 500,000-row CSV is no more openable for being zipped (ADR-0013)."""
    run = _add_run(
        run_repository, detail_store, name="BIG",
        sections={"Mismatches": pd.DataFrame({"a": range(25)})},
    )

    names = _zip_names(service.build_export([run.run_id], batch_rows=10))

    assert "FD_BIG/Mismatches_1.csv" in names
    assert "FD_BIG/Mismatches_3.csv" in names
    assert "FD_BIG/Mismatches.csv" not in names


def test_two_runs_of_the_same_suite_get_distinct_folders(
    service, run_repository, detail_store
) -> None:
    a = _add_run(run_repository, detail_store, name="NIGHTLY")
    b = _add_run(run_repository, detail_store, name="NIGHTLY")

    names = _zip_names(service.build_export([a.run_id, b.run_id]))
    folders = {n.split("/")[0] for n in names if "/" in n}

    assert len(folders) == 2
    assert "FD_NIGHTLY" in folders


def test_a_name_with_awkward_characters_is_safe_as_a_folder(
    service, run_repository, detail_store
) -> None:
    run = _add_run(run_repository, detail_store, name="ORDERS / EU · v2")

    names = _zip_names(service.build_export([run.run_id]))

    assert all("/" not in n.split("/")[0] for n in names)
    assert any(n.startswith("FD_ORDERS_EU_v2/") for n in names)


def test_an_unknown_run_is_skipped_rather_than_failing_the_export(
    service, run_repository, detail_store
) -> None:
    run = _add_run(run_repository, detail_store, name="ORDERS")

    names = _zip_names(service.build_export([run.run_id, "nope"]))

    assert "FD_ORDERS/summary.csv" in names


def test_an_empty_selection_still_produces_a_readable_archive(service) -> None:
    names = _zip_names(service.build_export([]))

    assert names == ["manifest.csv"]


def test_the_export_filename_names_the_count_and_time(service) -> None:
    name = service.export_filename(4, datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert name == "DataRecon_Runs_4_20260305_0630.zip"
