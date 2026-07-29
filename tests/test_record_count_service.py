"""Unit tests — RecordCountService (Module 3)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.record_count_service import (
    RecordCountRequest,
    RecordCountService,
)
from datarecon.domain.enums import RunStatus
from tests.conftest import FakeExtractionService


@pytest.fixture
def service(run_repository) -> RecordCountService:
    frames = {
        "src": pd.DataFrame({"id": range(100), "region": ["east"] * 60 + ["west"] * 40}),
        "tgt_exact": pd.DataFrame({"id": range(100), "region": ["east"] * 60 + ["west"] * 40}),
        "tgt_short": pd.DataFrame({"id": range(90), "region": ["east"] * 55 + ["west"] * 35}),
        "tgt_empty": pd.DataFrame({"id": [], "region": []}),
    }
    return RecordCountService(FakeExtractionService(frames), run_repository)


def test_exact_match_passes(service: RecordCountService) -> None:
    result = service.execute(
        RecordCountRequest(source_connection_id="src", target_connection_id="tgt_exact")
    )
    assert result.source_count == 100
    assert result.target_count == 100
    assert result.difference == 0
    assert result.status == RunStatus.PASS
    assert result.run.status == RunStatus.PASS


def test_mismatch_without_tolerance_fails(service: RecordCountService) -> None:
    result = service.execute(
        RecordCountRequest(source_connection_id="src", target_connection_id="tgt_short")
    )
    assert result.difference == -10
    assert result.variance_percent == 10.0
    assert result.status == RunStatus.FAIL


def test_mismatch_within_absolute_tolerance_passes(service: RecordCountService) -> None:
    result = service.execute(
        RecordCountRequest(
            source_connection_id="src", target_connection_id="tgt_short", tolerance_absolute=10
        )
    )
    assert result.status == RunStatus.PASS


def test_mismatch_within_percent_tolerance_passes(service: RecordCountService) -> None:
    result = service.execute(
        RecordCountRequest(
            source_connection_id="src", target_connection_id="tgt_short", tolerance_percent=15.0
        )
    )
    assert result.status == RunStatus.PASS


def test_empty_target_gives_full_variance(service: RecordCountService) -> None:
    result = service.execute(
        RecordCountRequest(source_connection_id="src", target_connection_id="tgt_empty")
    )
    assert result.target_count == 0
    assert result.variance_percent == 100.0
    assert result.status == RunStatus.FAIL


def test_group_by_breakdown(service: RecordCountService) -> None:
    result = service.execute(
        RecordCountRequest(
            source_connection_id="src", target_connection_id="tgt_short", group_by=["region"]
        )
    )
    assert result.source_count == 100
    assert result.target_count == 90
    breakdown = result.group_breakdown.set_index("region")
    assert breakdown.loc["east", "source_count"] == 60
    assert breakdown.loc["east", "target_count"] == 55
    assert breakdown.loc["west", "difference"] == -5


def test_persists_run_history(service: RecordCountService, run_repository) -> None:
    result = service.execute(
        RecordCountRequest(source_connection_id="src", target_connection_id="tgt_exact")
    )
    fetched = run_repository.get_by_id(result.run.run_id)
    assert fetched is not None
    assert fetched.summary["source_count"] == 100


def test_extraction_failure_records_error_run(service: RecordCountService, run_repository) -> None:
    with pytest.raises(ValueError, match="No fake frame"):
        service.execute(
            RecordCountRequest(source_connection_id="src", target_connection_id="does-not-exist")
        )
    runs = run_repository.list_recent()
    assert len(runs) == 1
    assert runs[0].status == RunStatus.ERROR
    assert "does-not-exist" in runs[0].error_message
