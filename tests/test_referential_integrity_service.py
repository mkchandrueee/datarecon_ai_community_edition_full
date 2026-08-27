"""Unit tests — ReferentialIntegrityService (orphan detection, ADR-0012)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.referential_integrity_service import (
    ReferentialIntegrityError,
    ReferentialIntegrityRequest,
    ReferentialIntegrityService,
)
from datarecon.domain.enums import RunStatus
from tests.conftest import FakeExtractionService


@pytest.fixture
def frames() -> dict[str, pd.DataFrame]:
    return {
        # Orders 3 and 4 reference customers that don't exist.
        "orders": pd.DataFrame(
            {
                "ORDER_ID": [1, 2, 3, 4],
                "CUSTOMER_ID": [10, 10, 99, 98],
                "AMOUNT": [5.0, 6.0, 7.0, 8.0],
            }
        ),
        "orders_clean": pd.DataFrame(
            {"ORDER_ID": [1, 2], "CUSTOMER_ID": [10, 20], "AMOUNT": [5.0, 6.0]}
        ),
        "orders_null_fk": pd.DataFrame(
            {"ORDER_ID": [1, 2, 3], "CUSTOMER_ID": [10, None, None], "AMOUNT": [5.0, 6.0, 7.0]}
        ),
        "orders_lower": pd.DataFrame({"order_id": [1, 2], "customer_id": [10, 99]}),
        "customers": pd.DataFrame({"CUSTOMER_ID": [10, 20], "NAME": ["a", "b"]}),
        "customers_dupe_keys": pd.DataFrame(
            {"CUSTOMER_ID": [10, 10, 20], "NAME": ["a", "a2", "b"]}
        ),
        "empty_customers": pd.DataFrame({"CUSTOMER_ID": [], "NAME": []}),
        # Composite key parent/child.
        "lines": pd.DataFrame(
            {"ORDER_ID": [1, 1, 2], "LINE_NO": [1, 2, 1], "SKU": ["x", "y", "z"]}
        ),
        "line_ref": pd.DataFrame({"ORDER_ID": [1, 1], "LINE_NO": [1, 2]}),
    }


@pytest.fixture
def service(frames, run_repository, detail_store) -> ReferentialIntegrityService:
    return ReferentialIntegrityService(
        FakeExtractionService(frames), run_repository, detail_store
    )


def _request(child="orders", parent="customers", **kwargs) -> ReferentialIntegrityRequest:
    defaults = {
        "child_connection_id": child,
        "child_columns": ["CUSTOMER_ID"],
        "parent_connection_id": parent,
        "parent_columns": ["CUSTOMER_ID"],
    }
    return ReferentialIntegrityRequest(**{**defaults, **kwargs})


def test_orphans_are_detected_and_fail_the_run(service) -> None:
    result = service.execute(_request())

    assert result.orphan_rows == 2
    assert result.distinct_orphan_keys == 2
    assert result.status == RunStatus.FAIL


def test_clean_data_passes(service) -> None:
    result = service.execute(_request(child="orders_clean"))

    assert result.orphan_rows == 0
    assert result.orphan_percent == 0.0
    assert result.status == RunStatus.PASS


def test_orphan_rows_are_returned_for_investigation(service) -> None:
    result = service.execute(_request())

    assert sorted(result.orphans["ORDER_ID"]) == [3, 4]
    assert "AMOUNT" in result.orphans.columns  # full child row, not just the key


def test_null_foreign_keys_are_not_orphans(service) -> None:
    """SQL treats a NULL FK as 'no reference', not a broken one — whether the
    NULL itself is acceptable is Nullability Validation's question."""
    result = service.execute(_request(child="orders_null_fk"))

    assert result.child_rows == 3
    assert result.null_key_rows == 2
    assert result.checked_rows == 1
    assert result.orphan_rows == 0
    assert result.status == RunStatus.PASS


def test_orphan_percent_is_of_checked_rows(service) -> None:
    result = service.execute(_request())
    assert result.orphan_percent == 50.0  # 2 orphans of 4 checked


def test_tolerance_allows_a_known_orphan_rate(service) -> None:
    result = service.execute(_request(tolerance_percent=50.0))
    assert result.orphan_rows == 2
    assert result.status == RunStatus.PASS


def test_duplicate_parent_keys_do_not_multiply_child_rows(service) -> None:
    """A parent with repeated key values must not fan the merge out."""
    result = service.execute(_request(child="orders_clean", parent="customers_dupe_keys"))

    assert result.checked_rows == 2
    assert result.orphan_rows == 0


def test_empty_parent_makes_every_child_row_an_orphan(service) -> None:
    result = service.execute(_request(parent="empty_customers"))
    assert result.orphan_rows == 4
    assert result.status == RunStatus.FAIL


def test_composite_keys(service) -> None:
    result = service.execute(
        _request(
            child="lines",
            parent="line_ref",
            child_columns=["ORDER_ID", "LINE_NO"],
            parent_columns=["ORDER_ID", "LINE_NO"],
        )
    )
    assert result.orphan_rows == 1  # (2, 1) is unreferenced
    assert result.orphans["SKU"].tolist() == ["z"]


def test_column_names_match_case_insensitively(service) -> None:
    """Child spells them lower-case, parent upper-case (ADR-0009)."""
    result = service.execute(
        _request(child="orders_lower", child_columns=["CUSTOMER_ID"])
    )
    assert result.checked_rows == 2
    assert result.orphan_rows == 1


def test_mismatched_key_arity_is_rejected(service) -> None:
    with pytest.raises(ReferentialIntegrityError, match="pair up"):
        service.execute(_request(child_columns=["A", "B"], parent_columns=["A"]))


def test_no_child_columns_is_rejected(service) -> None:
    with pytest.raises(ReferentialIntegrityError, match="At least one"):
        service.execute(_request(child_columns=[]))


def test_unknown_child_column_is_reported(service) -> None:
    with pytest.raises(ReferentialIntegrityError, match="Child column"):
        service.execute(_request(child_columns=["NOPE"], parent_columns=["CUSTOMER_ID"]))


def test_unknown_parent_column_is_reported(service) -> None:
    with pytest.raises(ReferentialIntegrityError, match="Parent column"):
        service.execute(_request(child_columns=["CUSTOMER_ID"], parent_columns=["NOPE"]))


def test_sample_limit_caps_returned_orphans(service) -> None:
    result = service.execute(_request(sample_limit=1))
    assert len(result.orphans) == 1
    assert result.orphan_rows == 2  # the count is still the true total


def test_run_is_persisted_with_summary(service, run_repository) -> None:
    result = service.execute(_request())

    fetched = run_repository.get_by_id(result.run.run_id)
    assert fetched is not None
    assert fetched.summary["orphan_rows"] == 2
    assert fetched.summary["checked_rows"] == 4


def test_orphan_rows_are_persisted_for_reports(service, detail_store) -> None:
    result = service.execute(_request())
    assert "Orphan Rows" in detail_store.list_sections(result.run.run_id)


def test_extraction_failure_records_an_error_run(service, run_repository) -> None:
    with pytest.raises(ValueError, match="No fake frame"):
        service.execute(_request(child="does_not_exist"))

    assert any(r.status == RunStatus.ERROR for r in run_repository.list_recent())
