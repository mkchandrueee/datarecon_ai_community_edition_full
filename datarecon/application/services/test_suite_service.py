# datarecon/application/services/test_suite_service.py
# Saves validation-module run configurations as named Test Suites under a
# Project so they can be re-run later for regression checks (ADR-0005).
# Each Request dataclass round-trips to a JSON-safe dict via
# `serialize_request()` / `_deserialize_request()`; scheduled/automatic
# execution is out of scope for Community Edition — `schedule_cron` /
# `schedule_enabled` on TestSuite only reserve the field for a later phase.
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

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
from datarecon.core.engine import ComparisonConfig
from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import AggregateFunction, RunStatus, ValidationModule
from datarecon.domain.interfaces.project_repository import IProjectRepository
from datarecon.domain.interfaces.test_suite_repository import ITestSuiteRepository

RUNNABLE_MODULES = (
    ValidationModule.SCHEMA,
    ValidationModule.RECORD_COUNT,
    ValidationModule.DUPLICATE,
    ValidationModule.NULLABILITY,
    ValidationModule.AGGREGATION,
    ValidationModule.FULL_DATA,
    ValidationModule.REFERENTIAL_INTEGRITY,
)


class TestSuiteError(ValueError):
    """Raised for malformed test-suite requests."""


def prefixed_name(module: ValidationModule, name: str) -> str:
    """Stamp the module's short code onto a suite name (RC_CUSTOMER_MASTER).

    Suites from different modules often describe the same table, so the bare
    name alone doesn't say what was validated; the prefix makes the module
    readable in suite lists and lets reports group by it. Idempotent — a name
    that already carries the right prefix (in any case) is returned unchanged,
    so re-saving never produces RC_RC_CUSTOMER_MASTER.
    """
    name = name.strip()
    prefix = f"{module.code}_"
    if name.casefold().startswith(prefix.casefold()):
        return prefix + name[len(prefix) :]
    return prefix + name


@dataclass
class TestSuiteRunOutcome:
    suite: TestSuite
    status: RunStatus
    run: ValidationRun | None
    error_message: str | None = None


def serialize_request(request: Any) -> dict[str, Any]:
    """Convert any validation-module Request dataclass into a JSON-safe dict."""
    return dataclasses.asdict(request)


class TestSuiteService:
    def __init__(
        self,
        repository: ITestSuiteRepository,
        project_repository: IProjectRepository,
        schema_service: SchemaValidationService,
        record_count_service: RecordCountService,
        duplicate_service: DuplicateValidationService,
        nullability_service: NullabilityValidationService,
        aggregation_service: AggregationValidationService,
        full_data_service: FullDataValidationService,
        referential_integrity_service: ReferentialIntegrityService,
    ):
        self._repo = repository
        self._projects = project_repository
        self._schema = schema_service
        self._record_count = record_count_service
        self._duplicate = duplicate_service
        self._nullability = nullability_service
        self._aggregation = aggregation_service
        self._full_data = full_data_service
        self._referential = referential_integrity_service

    # ---------- CRUD ----------
    def list_suites(self, project_id: str | None = None) -> list[TestSuite]:
        return self._repo.list_by_project(project_id) if project_id else self._repo.list_all()

    def get_suite(self, suite_id: str) -> TestSuite | None:
        return self._repo.get_by_id(suite_id)

    def save_suite(
        self,
        *,
        project_id: str,
        name: str,
        module: ValidationModule,
        config: dict[str, Any],
        description: str = "",
        source_connection_id: str | None = None,
        target_connection_id: str | None = None,
    ) -> TestSuite:
        name = name.strip()
        if not name:
            raise TestSuiteError("Test suite name is required.")
        if module not in RUNNABLE_MODULES:
            raise TestSuiteError(f"Saving '{module.value}' as a Test Suite is not supported yet.")
        if self._projects.get_by_id(project_id) is None:
            raise TestSuiteError(f"Project '{project_id}' not found.")
        suite = TestSuite(
            project_id=project_id,
            name=prefixed_name(module, name),
            module=module,
            config=config,
            description=description,
            source_connection_id=source_connection_id,
            target_connection_id=target_connection_id,
        )
        return self._repo.add(suite)

    def delete_suite(self, suite_id: str) -> bool:
        return self._repo.delete(suite_id)

    # ---------- execution (regression re-run) ----------
    def run_suite(self, suite_id: str) -> TestSuiteRunOutcome:
        suite = self._repo.get_by_id(suite_id)
        if suite is None:
            raise TestSuiteError(f"Test suite '{suite_id}' not found.")
        try:
            request = self._deserialize_request(suite.module, suite.config)
            request = dataclasses.replace(request, name=suite.name)
            status, run = self._execute(suite.module, request, suite.project_id, suite.suite_id)
        except Exception as exc:
            when = datetime.now(UTC)
            self._repo.record_run_result(suite.suite_id, None, RunStatus.ERROR, when)
            suite.last_run_id = None
            suite.last_run_status = RunStatus.ERROR
            suite.last_run_at = when
            return TestSuiteRunOutcome(suite, RunStatus.ERROR, None, error_message=str(exc))

        self._repo.record_run_result(suite.suite_id, run.run_id, status, run.finished_at)
        suite.last_run_id = run.run_id
        suite.last_run_status = status
        suite.last_run_at = run.finished_at
        return TestSuiteRunOutcome(suite, status, run)

    def _execute(
        self, module: ValidationModule, request: Any, project_id: str, suite_id: str
    ) -> tuple[RunStatus, ValidationRun]:
        if module == ValidationModule.SCHEMA:
            schema_result = self._schema.execute(request, project_id, suite_id)
            return schema_result.status, schema_result.run
        if module == ValidationModule.RECORD_COUNT:
            record_count_result = self._record_count.execute(request, project_id, suite_id)
            return record_count_result.status, record_count_result.run
        if module == ValidationModule.DUPLICATE:
            duplicate_result = self._duplicate.execute(request, project_id, suite_id)
            return duplicate_result.status, duplicate_result.run
        if module == ValidationModule.NULLABILITY:
            nullability_result = self._nullability.execute(request, project_id, suite_id)
            return nullability_result.status, nullability_result.run
        if module == ValidationModule.AGGREGATION:
            aggregation_result = self._aggregation.execute(request, project_id, suite_id)
            return aggregation_result.status, aggregation_result.run
        if module == ValidationModule.FULL_DATA:
            outcome = self._full_data.execute(request, project_id, suite_id)
            return outcome.run.status, outcome.run
        if module == ValidationModule.REFERENTIAL_INTEGRITY:
            ri_result = self._referential.execute(request, project_id, suite_id)
            return ri_result.status, ri_result.run
        raise TestSuiteError(f"Running '{module.value}' from a saved Test Suite is not supported.")

    @staticmethod
    def _deserialize_request(module: ValidationModule, config: dict[str, Any]) -> Any:
        data = dict(config)
        if module == ValidationModule.SCHEMA:
            return SchemaValidationRequest(**data)
        if module == ValidationModule.RECORD_COUNT:
            return RecordCountRequest(**data)
        if module == ValidationModule.DUPLICATE:
            return DuplicateValidationRequest(**data)
        if module == ValidationModule.NULLABILITY:
            return NullabilityValidationRequest(**data)
        if module == ValidationModule.AGGREGATION:
            specs = [
                AggregationSpec(
                    column=s["column"],
                    function=AggregateFunction(s["function"]),
                    alias=s.get("alias"),
                )
                for s in data.pop("aggregations", [])
            ]
            return AggregationValidationRequest(aggregations=specs, **data)
        if module == ValidationModule.REFERENTIAL_INTEGRITY:
            return ReferentialIntegrityRequest(**data)
        if module == ValidationModule.FULL_DATA:
            raw_config = data.pop("config", None)
            return FullValidationRequest(
                config=ComparisonConfig(**raw_config) if raw_config else None, **data
            )
        raise TestSuiteError(f"Module '{module.value}' cannot be reconstructed from a Test Suite.")
