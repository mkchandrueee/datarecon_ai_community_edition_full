# datarecon/application/services/file_checksum_service.py
# Module 13: File Comparison — checksum mode.
#
# The structure/count/full-data comparison modes of Module 13 reuse
# SchemaValidationService / RecordCountService / FullDataValidationService
# directly (a file connection is just another Connection category — see
# Module 1), so this file only adds what's genuinely new: a whole-file
# hash comparison for local File Source connections (ADR-0001).
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from datarecon.application.services.run_recording import record_run
from datarecon.domain.entities.project import DEFAULT_PROJECT_ID
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.enums import ConnectionCategory, RunStatus, ValidationModule
from datarecon.domain.interfaces.connection_repository import IConnectionRepository
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository

_HASH_CHUNK_SIZE = 1 << 20  # 1 MiB


class FileChecksumError(ValueError):
    """Raised for malformed checksum-comparison requests."""


@dataclass(frozen=True)
class FileChecksumRequest:
    source_connection_id: str
    target_connection_id: str
    algorithm: str = "sha256"
    name: str = "File Comparison (Checksum)"


@dataclass
class FileChecksumResult:
    source_checksum: str
    target_checksum: str
    match: bool
    status: RunStatus
    run: ValidationRun


class FileChecksumService:
    def __init__(
        self, connection_repository: IConnectionRepository, run_repository: IValidationRunRepository
    ):
        self._repo = connection_repository
        self._runs = run_repository

    def execute(
        self, request: FileChecksumRequest, project_id: str = DEFAULT_PROJECT_ID
    ) -> FileChecksumResult:
        started = datetime.now(UTC)
        try:
            source_path = self._require_file_path(request.source_connection_id)
            target_path = self._require_file_path(request.target_connection_id)
            source_checksum = self._hash_file(source_path, request.algorithm)
            target_checksum = self._hash_file(target_path, request.algorithm)
            match = source_checksum == target_checksum
            status = RunStatus.PASS if match else RunStatus.FAIL

            run = record_run(
                self._runs,
                ValidationModule.FILE_COMPARISON,
                request.name,
                started,
                status,
                source_connection_id=request.source_connection_id,
                target_connection_id=request.target_connection_id,
                summary={
                    "algorithm": request.algorithm,
                    "source_checksum": source_checksum,
                    "target_checksum": target_checksum,
                    "match": match,
                },
                project_id=project_id,
            )
            return FileChecksumResult(source_checksum, target_checksum, match, status, run)
        except Exception as exc:
            record_run(
                self._runs,
                ValidationModule.FILE_COMPARISON,
                request.name,
                started,
                RunStatus.ERROR,
                source_connection_id=request.source_connection_id,
                target_connection_id=request.target_connection_id,
                error_message=str(exc),
                project_id=project_id,
            )
            raise

    def _require_file_path(self, connection_id: str) -> str:
        conn = self._repo.get_by_id(connection_id)
        if conn is None:
            raise FileChecksumError(f"Connection '{connection_id}' not found.")
        if conn.category != ConnectionCategory.FILE:
            raise FileChecksumError(
                f"Checksum comparison requires a File Source connection; "
                f"'{conn.connection_name}' is {conn.category.value}."
            )
        if not conn.file_path:
            raise FileChecksumError(f"Connection '{conn.connection_name}' has no file path.")
        return conn.file_path

    @staticmethod
    def _hash_file(path: str, algorithm: str) -> str:
        if not Path(path).is_file():
            raise FileNotFoundError(f"File not found: {path}")
        digest = hashlib.new(algorithm)
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()
