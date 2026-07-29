"""Unit tests — AggregationValidationService (Module 7)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.aggregation_validation_service import (
    AggregationSpec,
    AggregationValidationError,
    AggregationValidationRequest,
    AggregationValidationService,
)
from datarecon.domain.enums import AggregateFunction, RunStatus
from tests.conftest import FakeExtractionService


@pytest.fixture
def service(run_repository) -> AggregationValidationService:
    frames = {
        "src": pd.DataFrame(
            {
                "region": ["east", "east", "west", "west"],
                "amount": [100.0, 200.0, 50.0, 50.0],
            }
        ),
        "tgt_exact": pd.DataFrame(
            {
                "region": ["east", "east", "west", "west"],
                "amount": [100.0, 200.0, 50.0, 50.0],
            }
        ),
        "tgt_off": pd.DataFrame(
            {
                "region": ["east", "east", "west", "west"],
                "amount": [100.0, 250.0, 50.0, 50.0],
            }
        ),
    }
    return AggregationValidationService(FakeExtractionService(frames), run_repository)


def test_sum_matches_and_passes(service: AggregationValidationService) -> None:
    result = service.execute(
        AggregationValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt_exact",
            aggregations=[AggregationSpec(column="amount", function=AggregateFunction.SUM)],
        )
    )
    assert result.status == RunStatus.PASS
    row = result.comparison.iloc[0]
    assert row["source_value"] == 400.0
    assert row["target_value"] == 400.0
    assert row["difference"] == 0.0


def test_sum_mismatch_fails(service: AggregationValidationService) -> None:
    result = service.execute(
        AggregationValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt_off",
            aggregations=[AggregationSpec(column="amount", function=AggregateFunction.SUM)],
        )
    )
    assert result.status == RunStatus.FAIL
    row = result.comparison.iloc[0]
    assert row["difference"] == 50.0


def test_mismatch_within_tolerance_passes(service: AggregationValidationService) -> None:
    result = service.execute(
        AggregationValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt_off",
            aggregations=[AggregationSpec(column="amount", function=AggregateFunction.SUM)],
            tolerance_percent=20.0,
        )
    )
    assert result.status == RunStatus.PASS


def test_multiple_aggregations(service: AggregationValidationService) -> None:
    result = service.execute(
        AggregationValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt_exact",
            aggregations=[
                AggregationSpec(column="amount", function=AggregateFunction.SUM),
                AggregationSpec(column="amount", function=AggregateFunction.AVG),
                AggregationSpec(column="region", function=AggregateFunction.COUNT_DISTINCT),
            ],
        )
    )
    assert set(result.comparison["metric"]) == {
        "SUM_amount",
        "AVG_amount",
        "COUNT_DISTINCT_region",
    }
    assert result.status == RunStatus.PASS


def test_group_by_breakdown(service: AggregationValidationService) -> None:
    result = service.execute(
        AggregationValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt_off",
            aggregations=[AggregationSpec(column="amount", function=AggregateFunction.SUM)],
            group_by=["region"],
        )
    )
    by_region = result.comparison.set_index("region")
    assert by_region.loc["east", "difference"] == 50.0
    assert by_region.loc["west", "difference"] == 0.0
    assert result.status == RunStatus.FAIL


def test_requires_at_least_one_aggregation(service: AggregationValidationService) -> None:
    with pytest.raises(AggregationValidationError, match="At least one"):
        service.execute(
            AggregationValidationRequest(
                source_connection_id="src", target_connection_id="tgt_exact", aggregations=[]
            )
        )


def test_unknown_column_raises(service: AggregationValidationService) -> None:
    with pytest.raises(AggregationValidationError, match="not found"):
        service.execute(
            AggregationValidationRequest(
                source_connection_id="src",
                target_connection_id="tgt_exact",
                aggregations=[
                    AggregationSpec(column="does_not_exist", function=AggregateFunction.SUM)
                ],
            )
        )


def test_persists_run_history(service: AggregationValidationService, run_repository) -> None:
    result = service.execute(
        AggregationValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt_exact",
            aggregations=[AggregationSpec(column="amount", function=AggregateFunction.SUM)],
        )
    )
    fetched = run_repository.get_by_id(result.run.run_id)
    assert fetched is not None
    assert fetched.summary["metrics_compared"] == 1
