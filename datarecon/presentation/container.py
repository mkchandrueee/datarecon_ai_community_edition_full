# datarecon/presentation/container.py
# Typed handle to the composition-root services (built once in app.py,
# threaded through every Streamlit view via st.session_state).
from __future__ import annotations

from dataclasses import dataclass

from datarecon.application.services.aggregation_validation_service import (
    AggregationValidationService,
)
from datarecon.application.services.connection_service import ConnectionService
from datarecon.application.services.dashboard_service import DashboardService
from datarecon.application.services.data_extraction_service import DataExtractionService
from datarecon.application.services.duplicate_validation_service import DuplicateValidationService
from datarecon.application.services.file_checksum_service import FileChecksumService
from datarecon.application.services.full_data_validation_service import FullDataValidationService
from datarecon.application.services.nullability_validation_service import (
    NullabilityValidationService,
)
from datarecon.application.services.profiling_service import ProfilingService
from datarecon.application.services.project_service import ProjectService
from datarecon.application.services.record_count_service import RecordCountService
from datarecon.application.services.referential_integrity_service import (
    ReferentialIntegrityService,
)
from datarecon.application.services.reporting_service import ReportingService
from datarecon.application.services.run_management_service import RunManagementService
from datarecon.application.services.scheduler_service import SchedulerService
from datarecon.application.services.schema_validation_service import SchemaValidationService
from datarecon.application.services.sql_generation_service import SqlGenerationService
from datarecon.application.services.suite_report_service import SuiteReportService
from datarecon.application.services.test_suite_service import TestSuiteService
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository
from datarecon.infrastructure.persistence.run_detail_store import RunDetailStore


@dataclass(frozen=True)
class ServiceContainer:
    connection_service: ConnectionService
    extraction_service: DataExtractionService
    schema_service: SchemaValidationService
    record_count_service: RecordCountService
    duplicate_service: DuplicateValidationService
    nullability_service: NullabilityValidationService
    aggregation_service: AggregationValidationService
    full_data_service: FullDataValidationService
    referential_integrity_service: ReferentialIntegrityService
    profiling_service: ProfilingService
    file_checksum_service: FileChecksumService
    reporting_service: ReportingService
    dashboard_service: DashboardService
    project_service: ProjectService
    test_suite_service: TestSuiteService
    suite_report_service: SuiteReportService
    sql_generation_service: SqlGenerationService
    scheduler_service: SchedulerService
    run_management_service: RunManagementService
    run_repository: IValidationRunRepository
    detail_store: RunDetailStore
