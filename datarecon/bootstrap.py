# datarecon/bootstrap.py
# Composition root: wires infrastructure into services (DI). It lives here
# rather than in app.py so that a process without Streamlit — the scheduler
# daemon (ADR-0014) — can build the same object graph the UI uses, instead of
# assembling a second, subtly different one.
from __future__ import annotations

from config.settings import settings
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
from datarecon.infrastructure.connectors.engine_factory import EngineFactory
from datarecon.infrastructure.extraction.data_extractor import DataExtractor
from datarecon.infrastructure.notifications.factory import build_notifier
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase
from datarecon.infrastructure.persistence.run_detail_store import RunDetailStore
from datarecon.infrastructure.persistence.sqlite_connection_repository import (
    SQLiteConnectionRepository,
)
from datarecon.infrastructure.persistence.sqlite_project_repository import (
    SQLiteProjectRepository,
)
from datarecon.infrastructure.persistence.sqlite_test_suite_repository import (
    SQLiteTestSuiteRepository,
)
from datarecon.infrastructure.persistence.sqlite_validation_run_repository import (
    SQLiteValidationRunRepository,
)
from datarecon.infrastructure.security.crypto import CredentialCipher
from datarecon.presentation.container import ServiceContainer


def build_container() -> ServiceContainer:
    """Build the full service graph from settings."""
    # 1. Initialize Infrastructure
    metadata_db = MetadataDatabase(settings.metadata_db_path)
    cipher = CredentialCipher(settings.encryption_key_path)
    connection_repository = SQLiteConnectionRepository(metadata_db)
    run_repository = SQLiteValidationRunRepository(metadata_db)
    project_repository = SQLiteProjectRepository(metadata_db)
    test_suite_repository = SQLiteTestSuiteRepository(metadata_db)
    engine_factory = EngineFactory()
    extractor = DataExtractor(engine_factory)
    detail_store = RunDetailStore(settings.run_detail_dir)

    # 2. Initialize Services
    extraction_service = DataExtractionService(connection_repository, cipher, extractor)
    schema_service = SchemaValidationService(extraction_service, run_repository, detail_store)
    record_count_service = RecordCountService(extraction_service, run_repository, detail_store)
    duplicate_service = DuplicateValidationService(extraction_service, run_repository, detail_store)
    nullability_service = NullabilityValidationService(
        extraction_service, run_repository, detail_store
    )
    aggregation_service = AggregationValidationService(
        extraction_service, run_repository, detail_store
    )
    reporting_service = ReportingService()
    full_data_service = FullDataValidationService(extraction_service, run_repository, detail_store)
    referential_integrity_service = ReferentialIntegrityService(
        extraction_service, run_repository, detail_store
    )
    test_suite_service = TestSuiteService(
        test_suite_repository,
        project_repository,
        schema_service,
        record_count_service,
        duplicate_service,
        nullability_service,
        aggregation_service,
        full_data_service,
        referential_integrity_service,
    )

    return ServiceContainer(
        connection_service=ConnectionService(connection_repository, cipher, engine_factory),
        extraction_service=extraction_service,
        schema_service=schema_service,
        record_count_service=record_count_service,
        duplicate_service=duplicate_service,
        nullability_service=nullability_service,
        aggregation_service=aggregation_service,
        full_data_service=full_data_service,
        referential_integrity_service=referential_integrity_service,
        profiling_service=ProfilingService(extraction_service, run_repository, detail_store),
        file_checksum_service=FileChecksumService(connection_repository, run_repository),
        reporting_service=reporting_service,
        dashboard_service=DashboardService(run_repository),
        project_service=ProjectService(project_repository),
        test_suite_service=test_suite_service,
        suite_report_service=SuiteReportService(test_suite_repository, run_repository),
        sql_generation_service=SqlGenerationService(extraction_service),
        scheduler_service=SchedulerService(
            repository=test_suite_repository,
            test_suite_service=test_suite_service,
            notifier=build_notifier(settings),
            timezone=settings.schedule_timezone,
            notify_on=settings.notify_on,
        ),
        run_management_service=RunManagementService(
            run_repository, detail_store, reporting_service
        ),
        run_repository=run_repository,
        detail_store=detail_store,
    )
