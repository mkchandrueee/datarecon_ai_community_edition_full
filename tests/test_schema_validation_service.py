"""Unit tests — SchemaValidationService (Module 2)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.schema_validation_service import (
    SchemaValidationRequest,
    SchemaValidationService,
)
from datarecon.domain.entities.column_catalog_metadata import ColumnCatalogMetadata
from datarecon.domain.enums import RunStatus
from tests.conftest import FakeExtractionService


@pytest.fixture
def service(run_repository, detail_store) -> SchemaValidationService:
    frames = {
        "src": pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "amount": [1.0, 2.0]}),
        "tgt_identical": pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "amount": [1.0, 2.0]}),
        "tgt_missing_col": pd.DataFrame({"id": [1, 2], "name": ["a", "b"]}),
        "tgt_extra_col": pd.DataFrame(
            {"id": [1, 2], "name": ["a", "b"], "amount": [1.0, 2.0], "extra": ["x", "y"]}
        ),
        "tgt_type_mismatch": pd.DataFrame(
            {"id": ["1", "2"], "name": ["a", "b"], "amount": [1.0, 2.0]}
        ),
        "tgt_reordered": pd.DataFrame({"name": ["a", "b"], "id": [1, 2], "amount": [1.0, 2.0]}),
    }
    return SchemaValidationService(FakeExtractionService(frames), run_repository, detail_store)


def test_identical_schema_passes(service: SchemaValidationService) -> None:
    result = service.execute(
        SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt_identical")
    )
    assert result.status == RunStatus.PASS
    assert (result.comparison["status"] == "MATCH").all()


def test_missing_column_fails(service: SchemaValidationService) -> None:
    result = service.execute(
        SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt_missing_col")
    )
    assert result.status == RunStatus.FAIL
    row = result.comparison.set_index("column").loc["amount"]
    assert row["status"] == "MISSING_IN_TARGET"
    assert pd.isna(row["target_position"])


def test_extra_column_fails(service: SchemaValidationService) -> None:
    result = service.execute(
        SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt_extra_col")
    )
    assert result.status == RunStatus.FAIL
    row = result.comparison.set_index("column").loc["extra"]
    assert row["status"] == "EXTRA_IN_TARGET"
    assert pd.isna(row["source_position"])


def test_type_mismatch_fails(service: SchemaValidationService) -> None:
    result = service.execute(
        SchemaValidationRequest(
            source_connection_id="src", target_connection_id="tgt_type_mismatch"
        )
    )
    assert result.status == RunStatus.FAIL
    row = result.comparison.set_index("column").loc["id"]
    assert row["status"] == "TYPE_MISMATCH"
    assert row["source_type"] == "INTEGER"
    assert row["target_type"] == "STRING"


def test_position_only_mismatch_does_not_fail_run(service: SchemaValidationService) -> None:
    result = service.execute(
        SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt_reordered")
    )
    assert result.status == RunStatus.PASS
    row = result.comparison.set_index("column").loc["id"]
    assert row["status"] == "POSITION_MISMATCH"


def test_persists_run_history(service: SchemaValidationService, run_repository) -> None:
    result = service.execute(
        SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt_missing_col")
    )
    fetched = run_repository.get_by_id(result.run.run_id)
    assert fetched is not None
    assert fetched.summary["mismatches"] == 1


def test_persists_row_level_detail(
    service: SchemaValidationService, detail_store, run_repository
) -> None:
    result = service.execute(
        SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt_missing_col")
    )
    sections = detail_store.load_all(result.run.run_id)
    assert set(sections) == {"Column Comparison"}
    pd.testing.assert_frame_equal(
        sections["Column Comparison"], result.comparison, check_dtype=False
    )


# ---------- catalog metadata enrichment (length/key/default, ADR-0007) ----------


def _catalog_service(run_repository, detail_store, catalogs) -> SchemaValidationService:
    frames = {
        "src": pd.DataFrame({"id": [1, 2], "name": ["a", "b"]}),
        "tgt": pd.DataFrame({"id": [1, 2], "name": ["a", "b"]}),
    }
    return SchemaValidationService(
        FakeExtractionService(frames, catalogs), run_repository, detail_store
    )


def test_catalog_not_fetched_without_table_name(run_repository, detail_store) -> None:
    service = _catalog_service(run_repository, detail_store, catalogs={})
    result = service.execute(
        SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt")
    )
    assert result.comparison["length_match"].isna().all()
    assert result.run.summary["attribute_mismatches"] == 0


def test_matching_catalog_attributes_pass(run_repository, detail_store) -> None:
    catalogs = {
        "src:customers": [
            ColumnCatalogMetadata("id", "INTEGER", None, False, None, True),
            ColumnCatalogMetadata("name", "VARCHAR(50)", 50, True, None, False),
        ],
        "tgt:customers": [
            ColumnCatalogMetadata("id", "INTEGER", None, False, None, True),
            ColumnCatalogMetadata("name", "VARCHAR(50)", 50, True, None, False),
        ],
    }
    service = _catalog_service(run_repository, detail_store, catalogs)
    result = service.execute(
        SchemaValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt",
            source_table="customers",
            target_table="customers",
        )
    )
    assert result.status == RunStatus.PASS
    assert result.run.summary["attribute_mismatches"] == 0
    row = result.comparison.set_index("column").loc["name"]
    assert bool(row["length_match"]) is True
    assert bool(row["key_match"]) is True
    assert bool(row["default_match"]) is True


def test_length_mismatch_fails(run_repository, detail_store) -> None:
    catalogs = {
        "src:customers": [ColumnCatalogMetadata("name", "VARCHAR(50)", 50, True, None, False)],
        "tgt:customers": [ColumnCatalogMetadata("name", "VARCHAR(20)", 20, True, None, False)],
    }
    service = _catalog_service(run_repository, detail_store, catalogs)
    result = service.execute(
        SchemaValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt",
            source_table="customers",
            target_table="customers",
        )
    )
    assert result.status == RunStatus.FAIL
    assert result.run.summary["attribute_mismatches"] == 1
    row = result.comparison.set_index("column").loc["name"]
    assert bool(row["length_match"]) is False
    assert row["source_length"] == 50
    assert row["target_length"] == 20


def test_key_column_mismatch_fails(run_repository, detail_store) -> None:
    catalogs = {
        "src:customers": [ColumnCatalogMetadata("id", "INTEGER", None, False, None, True)],
        "tgt:customers": [ColumnCatalogMetadata("id", "INTEGER", None, False, None, False)],
    }
    service = _catalog_service(run_repository, detail_store, catalogs)
    result = service.execute(
        SchemaValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt",
            source_table="customers",
            target_table="customers",
        )
    )
    assert result.status == RunStatus.FAIL
    row = result.comparison.set_index("column").loc["id"]
    assert bool(row["key_match"]) is False


def test_default_mismatch_fails(run_repository, detail_store) -> None:
    catalogs = {
        "src:customers": [ColumnCatalogMetadata("id", "INTEGER", None, True, "0", False)],
        "tgt:customers": [ColumnCatalogMetadata("id", "INTEGER", None, True, "1", False)],
    }
    service = _catalog_service(run_repository, detail_store, catalogs)
    result = service.execute(
        SchemaValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt",
            source_table="customers",
            target_table="customers",
        )
    )
    assert result.status == RunStatus.FAIL
    row = result.comparison.set_index("column").loc["id"]
    assert bool(row["default_match"]) is False


def test_custom_query_skips_catalog_lookup_even_with_table_set(run_repository, detail_store) -> None:
    catalogs = {
        "src:customers": [ColumnCatalogMetadata("id", "INTEGER", None, False, None, True)],
        "tgt:customers": [ColumnCatalogMetadata("id", "INTEGER", None, False, None, True)],
    }
    service = _catalog_service(run_repository, detail_store, catalogs)
    result = service.execute(
        SchemaValidationRequest(
            source_connection_id="src",
            target_connection_id="tgt",
            source_query="SELECT * FROM customers",  # query wins over table
            source_table="customers",
            target_table="customers",
        )
    )
    # source side used a query, so its catalog is never fetched -> nothing to compare
    assert result.comparison["length_match"].isna().all()
