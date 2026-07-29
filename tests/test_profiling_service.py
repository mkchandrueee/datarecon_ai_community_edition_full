"""Unit tests — ProfilingService (Module 10)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.profiling_service import (
    ProfilingError,
    ProfilingRequest,
    ProfilingService,
)
from datarecon.domain.enums import RunStatus
from tests.conftest import FakeExtractionService


@pytest.fixture
def service(run_repository) -> ProfilingService:
    frames = {
        "mixed": pd.DataFrame(
            {
                "id": list(range(1, 21)),
                "amount": [float(i) * 1.5 for i in range(20)],
                "email": [f"user{i}@example.com" for i in range(19)] + [None],
                "status": ["active"] * 15 + ["inactive"] * 5,
            }
        ),
        "empty": pd.DataFrame({"id": [], "name": []}),
    }
    return ProfilingService(FakeExtractionService(frames), run_repository)


def test_profiles_every_column_by_default(service: ProfilingService) -> None:
    result = service.execute(ProfilingRequest(connection_id="mixed"))
    assert result.total_rows == 20
    assert set(result.column_profiles["column"]) == {"id", "amount", "email", "status"}
    assert result.run.status == RunStatus.PASS


def test_numeric_stats_computed(service: ProfilingService) -> None:
    result = service.execute(ProfilingRequest(connection_id="mixed", columns=["amount"]))
    row = result.column_profiles.iloc[0]
    assert row["min"] == 0.0
    assert row["max"] == pytest.approx(28.5)
    assert row["null_count"] == 0


def test_null_count_and_percent(service: ProfilingService) -> None:
    result = service.execute(ProfilingRequest(connection_id="mixed", columns=["email"]))
    row = result.column_profiles.iloc[0]
    assert row["null_count"] == 1
    assert row["null_percent"] == 5.0


def test_email_semantic_type_detected(service: ProfilingService) -> None:
    result = service.execute(ProfilingRequest(connection_id="mixed", columns=["email"]))
    assert result.column_profiles.iloc[0]["semantic_type"] == "EMAIL"


def test_high_cardinality_numeric_is_id(service: ProfilingService) -> None:
    result = service.execute(ProfilingRequest(connection_id="mixed", columns=["id"]))
    assert result.column_profiles.iloc[0]["semantic_type"] == "NUMERIC_ID"


def test_low_cardinality_string_is_free_text(service: ProfilingService) -> None:
    result = service.execute(ProfilingRequest(connection_id="mixed", columns=["status"]))
    assert result.column_profiles.iloc[0]["semantic_type"] == "FREE_TEXT"


def test_top_values_frequency(service: ProfilingService) -> None:
    result = service.execute(ProfilingRequest(connection_id="mixed", columns=["status"], top_n=2))
    top = result.top_values["status"]
    assert list(top["value"]) == ["active", "inactive"]
    assert int(top.loc[top["value"] == "active", "frequency"].iloc[0]) == 15


def test_empty_dataset(service: ProfilingService) -> None:
    result = service.execute(ProfilingRequest(connection_id="empty"))
    assert result.total_rows == 0
    assert (result.column_profiles["null_percent"] == 0.0).all()


def test_missing_column_raises(service: ProfilingService) -> None:
    with pytest.raises(ProfilingError, match="not found"):
        service.execute(ProfilingRequest(connection_id="mixed", columns=["does_not_exist"]))


def test_persists_run_history(service: ProfilingService, run_repository) -> None:
    result = service.execute(ProfilingRequest(connection_id="mixed"))
    fetched = run_repository.get_by_id(result.run.run_id)
    assert fetched is not None
    assert fetched.summary["total_rows"] == 20
