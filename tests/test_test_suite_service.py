"""Unit tests — TestSuiteService (save/list/run saved validation configs, ADR-0005)."""

from __future__ import annotations

import pandas as pd
import pytest

from datarecon.application.services.aggregation_validation_service import (
    AggregationSpec,
    AggregationValidationRequest,
    AggregationValidationService,
)
from datarecon.application.services.duplicate_validation_service import (
    DuplicateValidationRequest,
    DuplicateValidationService,
)
from datarecon.application.services.full_data_validation_service import (
    FullDataValidationService,
    FullValidationRequest,
)
from datarecon.application.services.nullability_validation_service import (
    NullabilityValidationRequest,
    NullabilityValidationService,
)
from datarecon.application.services.record_count_service import (
    RecordCountRequest,
    RecordCountService,
)
from datarecon.application.services.referential_integrity_service import (
    ReferentialIntegrityRequest,
    ReferentialIntegrityService,
)
from datarecon.application.services.schema_validation_service import (
    SchemaValidationRequest,
    SchemaValidationService,
)
from datarecon.application.services.test_suite_service import (
    TestSuiteError,
    TestSuiteService,
    prefixed_name,
    serialize_request,
)
from datarecon.core.engine import ComparisonConfig
from datarecon.domain.entities.project import Project
from datarecon.domain.enums import AggregateFunction, RunStatus, ValidationModule
from tests.conftest import FakeExtractionService


@pytest.fixture
def frames() -> dict[str, pd.DataFrame]:
    return {
        "src": pd.DataFrame({"id": [1, 2, 3], "amount": [10.0, 20.0, 30.0]}),
        "tgt": pd.DataFrame({"id": [1, 2, 3], "amount": [10.0, 20.0, 30.0]}),
        "tgt_mismatch": pd.DataFrame({"id": [1, 2], "amount": [10.0, 20.0]}),
    }


@pytest.fixture
def service(
    run_repository, test_suite_repository, project_repository, detail_store, frames
) -> TestSuiteService:
    extraction = FakeExtractionService(frames)
    return TestSuiteService(
        test_suite_repository,
        project_repository,
        SchemaValidationService(extraction, run_repository, detail_store),
        RecordCountService(extraction, run_repository, detail_store),
        DuplicateValidationService(extraction, run_repository, detail_store),
        NullabilityValidationService(extraction, run_repository, detail_store),
        AggregationValidationService(extraction, run_repository, detail_store),
        FullDataValidationService(extraction, run_repository, detail_store),
        ReferentialIntegrityService(extraction, run_repository, detail_store),
    )


def _basic_config() -> dict:
    return {"source_connection_id": "src", "target_connection_id": "tgt"}


def test_save_suite(service: TestSuiteService) -> None:
    suite = service.save_suite(
        project_id="default",
        name="Customers schema",
        module=ValidationModule.SCHEMA,
        config=_basic_config(),
        source_connection_id="src",
        target_connection_id="tgt",
    )
    assert suite.name == "SC_Customers schema"  # module code prefix
    assert service.get_suite(suite.suite_id) is not None


def test_save_suite_requires_name(service: TestSuiteService) -> None:
    with pytest.raises(TestSuiteError, match="name is required"):
        service.save_suite(
            project_id="default", name="  ", module=ValidationModule.SCHEMA, config={}
        )


def test_save_suite_rejects_unsupported_module(service: TestSuiteService) -> None:
    with pytest.raises(TestSuiteError, match="not supported"):
        service.save_suite(
            project_id="default", name="x", module=ValidationModule.PROFILING, config={}
        )


def test_save_suite_rejects_unknown_project(service: TestSuiteService) -> None:
    with pytest.raises(TestSuiteError, match="not found"):
        service.save_suite(project_id="ghost", name="x", module=ValidationModule.SCHEMA, config={})


def test_delete_suite(service: TestSuiteService) -> None:
    suite = service.save_suite(
        project_id="default", name="x", module=ValidationModule.SCHEMA, config=_basic_config()
    )
    assert service.delete_suite(suite.suite_id) is True
    assert service.get_suite(suite.suite_id) is None


def test_list_suites_filters_by_project(
    service: TestSuiteService, project_repository
) -> None:
    other = project_repository.add(Project(name="Other"))
    service.save_suite(
        project_id="default", name="a", module=ValidationModule.SCHEMA, config=_basic_config()
    )
    service.save_suite(
        project_id=other.project_id,
        name="b",
        module=ValidationModule.SCHEMA,
        config=_basic_config(),
    )

    assert [s.name for s in service.list_suites("default")] == ["SC_a"]
    assert len(service.list_suites()) == 2


def test_run_suite_unknown_id_raises(service: TestSuiteService) -> None:
    with pytest.raises(TestSuiteError, match="not found"):
        service.run_suite("does-not-exist")


def test_run_suite_schema(service: TestSuiteService) -> None:
    request = SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt")
    suite = service.save_suite(
        project_id="default",
        name="schema check",
        module=ValidationModule.SCHEMA,
        config=serialize_request(request),
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.status == RunStatus.PASS
    assert outcome.run is not None
    assert outcome.error_message is None

    refreshed = service.get_suite(suite.suite_id)
    assert refreshed is not None
    assert refreshed.last_run_status == RunStatus.PASS
    assert refreshed.last_run_id == outcome.run.run_id


def test_run_suite_tags_run_with_suite_id_and_name(service: TestSuiteService) -> None:
    request = SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt")
    suite = service.save_suite(
        project_id="default",
        name="Nightly schema check",
        module=ValidationModule.SCHEMA,
        config=serialize_request(request),
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.run is not None
    assert outcome.run.suite_id == suite.suite_id
    assert outcome.run.name == "SC_Nightly schema check"


def test_run_suite_record_count_with_group_by(service: TestSuiteService) -> None:
    request = RecordCountRequest(
        source_connection_id="src", target_connection_id="tgt_mismatch", group_by=["id"]
    )
    suite = service.save_suite(
        project_id="default",
        name="record count",
        module=ValidationModule.RECORD_COUNT,
        config=serialize_request(request),
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.status == RunStatus.FAIL


def test_run_suite_duplicate(service: TestSuiteService) -> None:
    request = DuplicateValidationRequest(connection_id="src", key_columns=["id"])
    suite = service.save_suite(
        project_id="default",
        name="dup check",
        module=ValidationModule.DUPLICATE,
        config=serialize_request(request),
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.status == RunStatus.PASS


def test_run_suite_nullability(service: TestSuiteService) -> None:
    request = NullabilityValidationRequest(connection_id="src")
    suite = service.save_suite(
        project_id="default",
        name="nullability check",
        module=ValidationModule.NULLABILITY,
        config=serialize_request(request),
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.status == RunStatus.PASS


def test_run_suite_aggregation_roundtrips_specs(service: TestSuiteService) -> None:
    request = AggregationValidationRequest(
        source_connection_id="src",
        target_connection_id="tgt",
        aggregations=[AggregationSpec(column="amount", function=AggregateFunction.SUM)],
    )
    suite = service.save_suite(
        project_id="default",
        name="agg check",
        module=ValidationModule.AGGREGATION,
        config=serialize_request(request),
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.status == RunStatus.PASS


def test_run_suite_full_data_roundtrips_comparison_config(service: TestSuiteService) -> None:
    request = FullValidationRequest(
        source_connection_id="src",
        target_connection_id="tgt",
        business_keys=["id"],
        config=ComparisonConfig(trim_strings=True),
    )
    suite = service.save_suite(
        project_id="default",
        name="full data check",
        module=ValidationModule.FULL_DATA,
        config=serialize_request(request),
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.status == RunStatus.PASS


def test_run_suite_tags_run_with_suite_project(
    service: TestSuiteService, project_repository
) -> None:
    other = project_repository.add(Project(name="Migration Q1"))
    request = SchemaValidationRequest(source_connection_id="src", target_connection_id="tgt")
    suite = service.save_suite(
        project_id=other.project_id,
        name="schema check",
        module=ValidationModule.SCHEMA,
        config=serialize_request(request),
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.run is not None
    assert outcome.run.project_id == other.project_id


def test_run_suite_records_error_for_missing_connection(service: TestSuiteService) -> None:
    suite = service.save_suite(
        project_id="default",
        name="broken",
        module=ValidationModule.SCHEMA,
        config={"source_connection_id": "ghost", "target_connection_id": "tgt"},
    )
    outcome = service.run_suite(suite.suite_id)
    assert outcome.status == RunStatus.ERROR
    assert outcome.run is None
    assert outcome.error_message is not None

    refreshed = service.get_suite(suite.suite_id)
    assert refreshed is not None
    assert refreshed.last_run_status == RunStatus.ERROR


# ---------- module-code name prefixing ----------


def test_prefixed_name_stamps_module_code() -> None:
    assert (
        prefixed_name(ValidationModule.RECORD_COUNT, "CUSTOMER_MASTER")
        == "RC_CUSTOMER_MASTER"
    )
    assert prefixed_name(ValidationModule.SCHEMA, "ORDERS") == "SC_ORDERS"
    assert prefixed_name(ValidationModule.FULL_DATA, "ORDERS") == "FD_ORDERS"


def test_prefixed_name_is_idempotent() -> None:
    once = prefixed_name(ValidationModule.RECORD_COUNT, "CUSTOMER_MASTER")
    assert prefixed_name(ValidationModule.RECORD_COUNT, once) == once


def test_prefixed_name_normalises_existing_prefix_case() -> None:
    assert prefixed_name(ValidationModule.RECORD_COUNT, "rc_ORDERS") == "RC_ORDERS"


def test_prefixed_name_trims_whitespace() -> None:
    assert prefixed_name(ValidationModule.SCHEMA, "  ORDERS  ") == "SC_ORDERS"


def test_save_suite_applies_the_prefix(service: TestSuiteService) -> None:
    suite = service.save_suite(
        project_id="default",
        name="CUSTOMER_MASTER",
        module=ValidationModule.RECORD_COUNT,
        config=_basic_config(),
    )
    assert suite.name == "RC_CUSTOMER_MASTER"


def test_save_suite_does_not_double_prefix(service: TestSuiteService) -> None:
    suite = service.save_suite(
        project_id="default",
        name="RC_CUSTOMER_MASTER",
        module=ValidationModule.RECORD_COUNT,
        config=_basic_config(),
    )
    assert suite.name == "RC_CUSTOMER_MASTER"


def test_every_module_has_a_distinct_code() -> None:
    codes = [m.code for m in ValidationModule]
    assert len(codes) == len(set(codes))


def test_run_suite_referential_integrity_roundtrips(service: TestSuiteService) -> None:
    request = ReferentialIntegrityRequest(
        child_connection_id="src",
        child_columns=["id"],
        parent_connection_id="tgt",
        parent_columns=["id"],
    )
    suite = service.save_suite(
        project_id="default",
        name="ORDERS_FK",
        module=ValidationModule.REFERENTIAL_INTEGRITY,
        config=serialize_request(request),
    )
    assert suite.name == "RI_ORDERS_FK"

    outcome = service.run_suite(suite.suite_id)

    assert outcome.error_message is None
    assert outcome.run is not None
    assert outcome.run.module == ValidationModule.REFERENTIAL_INTEGRITY
    assert outcome.run.summary["orphan_rows"] == 0
