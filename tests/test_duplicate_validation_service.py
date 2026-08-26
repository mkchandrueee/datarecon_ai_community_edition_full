"""Unit tests — DuplicateValidationService (Module 4)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.duplicate_validation_service import (
    DuplicateValidationError,
    DuplicateValidationRequest,
    DuplicateValidationService,
)
from datarecon.domain.enums import RunStatus
from tests.conftest import FakeExtractionService


@pytest.fixture
def service(run_repository, detail_store) -> DuplicateValidationService:
    frames = {
        "clean": pd.DataFrame({"id": [1, 2, 3, 4], "name": ["a", "b", "c", "d"]}),
        "with_dups": pd.DataFrame(
            {
                "id": [1, 1, 1, 2, 3, 3],
                "name": ["a", "a-dup1", "a-dup2", "b", "c", "c-dup"],
            }
        ),
        "composite": pd.DataFrame(
            {
                "region": ["east", "east", "east", "west"],
                "id": [1, 1, 2, 1],
            }
        ),
    }
    return DuplicateValidationService(FakeExtractionService(frames), run_repository, detail_store)


def test_no_duplicates_passes(service: DuplicateValidationService) -> None:
    result = service.execute(DuplicateValidationRequest(connection_id="clean", key_columns=["id"]))
    assert result.total_rows == 4
    assert result.duplicate_key_count == 0
    assert result.duplicate_row_count == 0
    assert result.duplicate_percent == 0.0
    assert result.status == RunStatus.PASS
    assert result.duplicates.empty


def test_duplicates_detected_and_fails(service: DuplicateValidationService) -> None:
    result = service.execute(
        DuplicateValidationRequest(connection_id="with_dups", key_columns=["id"])
    )
    assert result.total_rows == 6
    assert result.duplicate_key_count == 2  # id=1 (x3), id=3 (x2)
    assert result.duplicate_row_count == 5  # 3 + 2
    assert result.status == RunStatus.FAIL
    assert set(result.duplicates["id"]) == {1, 3}
    assert len(result.duplicates) == 5


def test_composite_key_duplicates(service: DuplicateValidationService) -> None:
    result = service.execute(
        DuplicateValidationRequest(connection_id="composite", key_columns=["region", "id"])
    )
    assert result.duplicate_key_count == 1  # (east, 1) appears twice
    assert result.duplicate_row_count == 2


def test_sample_limit_caps_returned_rows(service: DuplicateValidationService) -> None:
    result = service.execute(
        DuplicateValidationRequest(connection_id="with_dups", key_columns=["id"], sample_limit=2)
    )
    assert len(result.duplicates) == 2


def test_requires_key_columns(service: DuplicateValidationService) -> None:
    with pytest.raises(DuplicateValidationError, match="key column"):
        service.execute(DuplicateValidationRequest(connection_id="clean", key_columns=[]))


def test_missing_key_column_raises(service: DuplicateValidationService) -> None:
    with pytest.raises(DuplicateValidationError, match="not found"):
        service.execute(
            DuplicateValidationRequest(connection_id="clean", key_columns=["does_not_exist"])
        )


def test_persists_run_history(service: DuplicateValidationService, run_repository) -> None:
    result = service.execute(
        DuplicateValidationRequest(connection_id="with_dups", key_columns=["id"])
    )
    fetched = run_repository.get_by_id(result.run.run_id)
    assert fetched is not None
    assert fetched.summary["duplicate_row_count"] == 5


def test_persists_duplicate_rows_detail_when_duplicates_found(
    service: DuplicateValidationService, detail_store
) -> None:
    result = service.execute(
        DuplicateValidationRequest(connection_id="with_dups", key_columns=["id"])
    )
    sections = detail_store.load_all(result.run.run_id)
    assert set(sections) == {"Duplicate Rows"}
    pd.testing.assert_frame_equal(sections["Duplicate Rows"], result.duplicates, check_dtype=False)


def test_no_detail_persisted_when_no_duplicates(
    service: DuplicateValidationService, detail_store
) -> None:
    result = service.execute(DuplicateValidationRequest(connection_id="clean", key_columns=["id"]))
    assert detail_store.list_sections(result.run.run_id) == []
