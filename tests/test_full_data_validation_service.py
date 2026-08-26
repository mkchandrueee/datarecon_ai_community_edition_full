"""Unit tests — FullDataValidationService (Module 6 orchestration + run history)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.full_data_validation_service import (
    FullDataValidationService,
    FullValidationRequest,
)
from datarecon.domain.enums import RunStatus
from tests.conftest import FakeExtractionService


@pytest.fixture
def service(run_repository, detail_store) -> FullDataValidationService:
    frames = {
        "src": pd.DataFrame({"id": [1, 2, 3], "amount": [10.0, 20.0, 30.0]}),
        "tgt_exact": pd.DataFrame({"id": [1, 2, 3], "amount": [10.0, 20.0, 30.0]}),
        "tgt_mismatch": pd.DataFrame({"id": [1, 2, 4], "amount": [10.0, 99.0, 40.0]}),
    }
    return FullDataValidationService(FakeExtractionService(frames), run_repository, detail_store)


def test_exact_match_passes_and_records_run(
    service: FullDataValidationService, run_repository
) -> None:
    outcome = service.execute(
        FullValidationRequest(
            source_connection_id="src", target_connection_id="tgt_exact", business_keys=["id"]
        )
    )
    assert outcome.result.is_passed()
    assert outcome.run.status == RunStatus.PASS
    fetched = run_repository.get_by_id(outcome.run.run_id)
    assert fetched is not None
    assert fetched.summary["success_percentage"] == 100.0


def test_project_id_defaults_and_can_be_overridden(
    service: FullDataValidationService, run_repository
) -> None:
    default_outcome = service.execute(
        FullValidationRequest(
            source_connection_id="src", target_connection_id="tgt_exact", business_keys=["id"]
        )
    )
    assert default_outcome.run.project_id == "default"

    tagged_outcome = service.execute(
        FullValidationRequest(
            source_connection_id="src", target_connection_id="tgt_exact", business_keys=["id"]
        ),
        project_id="proj-a",
    )
    assert tagged_outcome.run.project_id == "proj-a"
    fetched = run_repository.get_by_id(tagged_outcome.run.run_id)
    assert fetched is not None
    assert fetched.project_id == "proj-a"


def test_persists_all_four_detail_sections(
    service: FullDataValidationService, detail_store
) -> None:
    outcome = service.execute(
        FullValidationRequest(
            source_connection_id="src", target_connection_id="tgt_mismatch", business_keys=["id"]
        )
    )
    sections = detail_store.load_all(outcome.run.run_id)
    assert set(sections) == {"Mismatches", "Missing in Target", "Extra in Target", "Matched"}
    pd.testing.assert_frame_equal(sections["Mismatches"], outcome.result.mismatch, check_dtype=False)
    pd.testing.assert_frame_equal(
        sections["Missing in Target"], outcome.result.missing_in_target, check_dtype=False
    )
    pd.testing.assert_frame_equal(
        sections["Extra in Target"], outcome.result.extra_in_target, check_dtype=False
    )
    pd.testing.assert_frame_equal(sections["Matched"], outcome.result.exact_match, check_dtype=False)


def test_mismatch_fails_and_records_run(service: FullDataValidationService) -> None:
    outcome = service.execute(
        FullValidationRequest(
            source_connection_id="src", target_connection_id="tgt_mismatch", business_keys=["id"]
        )
    )
    assert not outcome.result.is_passed()
    assert outcome.run.status == RunStatus.FAIL
    assert outcome.run.summary["rows_mismatched"] == 1
    assert outcome.run.summary["rows_missing_in_target"] == 1
    assert outcome.run.summary["rows_extra_in_target"] == 1


def test_extraction_failure_records_error_run(
    service: FullDataValidationService, run_repository
) -> None:
    with pytest.raises(ValueError, match="No fake frame"):
        service.execute(
            FullValidationRequest(
                source_connection_id="src",
                target_connection_id="does-not-exist",
                business_keys=["id"],
            )
        )
    runs = run_repository.list_recent()
    assert len(runs) == 1
    assert runs[0].status == RunStatus.ERROR


def test_engine_error_records_error_run(service: FullDataValidationService, run_repository) -> None:
    with pytest.raises(Exception):  # noqa: B017 - SchemaAlignmentError from the engine
        service.execute(
            FullValidationRequest(
                source_connection_id="src",
                target_connection_id="tgt_exact",
                business_keys=["does_not_exist"],
            )
        )
    runs = run_repository.list_recent()
    assert runs[0].status == RunStatus.ERROR
