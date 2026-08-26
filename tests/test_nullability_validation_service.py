"""Unit tests — NullabilityValidationService (Module 5)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.nullability_validation_service import (
    NullabilityValidationError,
    NullabilityValidationRequest,
    NullabilityValidationService,
)
from datarecon.domain.enums import RunStatus
from tests.conftest import FakeExtractionService


@pytest.fixture
def service(run_repository, detail_store) -> NullabilityValidationService:
    frames = {
        "clean": pd.DataFrame({"id": [1, 2, 3, 4], "name": ["a", "b", "c", "d"]}),
        "messy": pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "email": [
                    "a@x.com",
                    None,
                    "  ",
                    "N/A",
                    "b@x.com",
                    "c@x.com",
                    "d@x.com",
                    "e@x.com",
                    "f@x.com",
                    "g@x.com",
                ],
            }
        ),
        "empty": pd.DataFrame({"id": [], "name": []}),
    }
    return NullabilityValidationService(FakeExtractionService(frames), run_repository, detail_store)


def test_fully_complete_data_passes(service: NullabilityValidationService) -> None:
    result = service.execute(NullabilityValidationRequest(connection_id="clean"))
    assert result.total_rows == 4
    assert result.completeness_score == 100.0
    assert result.status == RunStatus.PASS
    assert (result.column_stats["missing_count"] == 0).all()


def test_null_blank_and_sentinel_detected(service: NullabilityValidationService) -> None:
    result = service.execute(NullabilityValidationRequest(connection_id="messy", columns=["email"]))
    row = result.column_stats.iloc[0]
    assert row["null_count"] == 1
    assert row["blank_count"] == 1
    assert row["sentinel_count"] == 1
    assert row["missing_count"] == 3
    assert row["completeness_percent"] == 70.0
    assert result.status == RunStatus.FAIL


def test_completeness_threshold_allows_partial_pass(service: NullabilityValidationService) -> None:
    result = service.execute(
        NullabilityValidationRequest(
            connection_id="messy", columns=["email"], completeness_threshold_percent=50.0
        )
    )
    assert result.status == RunStatus.PASS


def test_defaults_to_all_columns(service: NullabilityValidationService) -> None:
    result = service.execute(NullabilityValidationRequest(connection_id="messy"))
    assert set(result.column_stats["column"]) == {"id", "email"}


def test_empty_dataset_is_fully_complete(service: NullabilityValidationService) -> None:
    result = service.execute(NullabilityValidationRequest(connection_id="empty"))
    assert result.total_rows == 0
    assert result.completeness_score == 100.0
    assert result.status == RunStatus.PASS


def test_missing_column_raises(service: NullabilityValidationService) -> None:
    with pytest.raises(NullabilityValidationError, match="not found"):
        service.execute(
            NullabilityValidationRequest(connection_id="clean", columns=["does_not_exist"])
        )


def test_custom_sentinel_values(service: NullabilityValidationService) -> None:
    result = service.execute(
        NullabilityValidationRequest(
            connection_id="messy", columns=["email"], sentinel_values=["N/A", "b@x.com"]
        )
    )
    row = result.column_stats.iloc[0]
    assert row["sentinel_count"] == 2  # "N/A" and "b@x.com"


def test_persists_run_history(service: NullabilityValidationService, run_repository) -> None:
    result = service.execute(NullabilityValidationRequest(connection_id="clean"))
    fetched = run_repository.get_by_id(result.run.run_id)
    assert fetched is not None
    assert fetched.summary["completeness_score"] == 100.0


def test_persists_column_statistics_detail(
    service: NullabilityValidationService, detail_store
) -> None:
    result = service.execute(NullabilityValidationRequest(connection_id="clean"))
    sections = detail_store.load_all(result.run.run_id)
    assert set(sections) == {"Column Statistics"}
    pd.testing.assert_frame_equal(
        sections["Column Statistics"], result.column_stats, check_dtype=False
    )
