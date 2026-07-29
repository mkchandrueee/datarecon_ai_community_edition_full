"""Unit tests — FileChecksumService (Module 13, checksum mode)."""

from __future__ import annotations

from pathlib import Path

import pytest

from datarecon.application.services.file_checksum_service import (
    FileChecksumError,
    FileChecksumRequest,
    FileChecksumService,
)
from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import ConnectionRole, DatabaseType, RunStatus
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase
from datarecon.infrastructure.persistence.sqlite_connection_repository import (
    SQLiteConnectionRepository,
)
from datarecon.infrastructure.persistence.sqlite_validation_run_repository import (
    SQLiteValidationRunRepository,
)


@pytest.fixture
def repo(tmp_path: Path) -> SQLiteConnectionRepository:
    db = MetadataDatabase(tmp_path / "meta.db")
    return SQLiteConnectionRepository(db)


@pytest.fixture
def run_repo(tmp_path: Path) -> SQLiteValidationRunRepository:
    db = MetadataDatabase(tmp_path / "runs.db")
    return SQLiteValidationRunRepository(db)


@pytest.fixture
def service(repo, run_repo) -> FileChecksumService:
    return FileChecksumService(repo, run_repo)


def _file_conn(repo, name: str, path: Path, content: str) -> str:
    path.write_text(content)
    conn = Connection(
        connection_name=name,
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
        file_path=str(path),
    )
    repo.add(conn)
    return conn.connection_id


def test_identical_files_match(service: FileChecksumService, repo, tmp_path: Path) -> None:
    src_id = _file_conn(repo, "src", tmp_path / "a.csv", "id,name\n1,alice\n")
    tgt_id = _file_conn(repo, "tgt", tmp_path / "b.csv", "id,name\n1,alice\n")

    result = service.execute(
        FileChecksumRequest(source_connection_id=src_id, target_connection_id=tgt_id)
    )

    assert result.match is True
    assert result.source_checksum == result.target_checksum
    assert result.status == RunStatus.PASS


def test_different_files_do_not_match(service: FileChecksumService, repo, tmp_path: Path) -> None:
    src_id = _file_conn(repo, "src", tmp_path / "a.csv", "id,name\n1,alice\n")
    tgt_id = _file_conn(repo, "tgt", tmp_path / "b.csv", "id,name\n1,bob\n")

    result = service.execute(
        FileChecksumRequest(source_connection_id=src_id, target_connection_id=tgt_id)
    )

    assert result.match is False
    assert result.source_checksum != result.target_checksum
    assert result.status == RunStatus.FAIL


def test_unknown_connection_raises(service: FileChecksumService, repo, tmp_path: Path) -> None:
    src_id = _file_conn(repo, "src", tmp_path / "a.csv", "x")
    with pytest.raises(FileChecksumError, match="not found"):
        service.execute(
            FileChecksumRequest(source_connection_id=src_id, target_connection_id="does-not-exist")
        )


def test_non_file_connection_raises(service: FileChecksumService, repo, tmp_path: Path) -> None:
    src_id = _file_conn(repo, "src", tmp_path / "a.csv", "x")
    db_conn = Connection(
        connection_name="pg",
        connection_role=ConnectionRole.TARGET,
        database_type=DatabaseType.POSTGRESQL,
        host="db",
        username="u",
    )
    repo.add(db_conn)

    with pytest.raises(FileChecksumError, match="File Source"):
        service.execute(
            FileChecksumRequest(
                source_connection_id=src_id, target_connection_id=db_conn.connection_id
            )
        )


def test_missing_file_raises(service: FileChecksumService, repo, run_repo, tmp_path: Path) -> None:
    conn = Connection(
        connection_name="ghost",
        connection_role=ConnectionRole.SOURCE,
        database_type=DatabaseType.CSV,
        file_path=str(tmp_path / "does-not-exist.csv"),
    )
    repo.add(conn)
    src_id = _file_conn(repo, "src", tmp_path / "a.csv", "x")

    with pytest.raises(FileNotFoundError):
        service.execute(
            FileChecksumRequest(
                source_connection_id=src_id, target_connection_id=conn.connection_id
            )
        )
    runs = run_repo.list_recent()
    assert runs[0].status == RunStatus.ERROR


def test_persists_run_history(service: FileChecksumService, repo, run_repo, tmp_path: Path) -> None:
    src_id = _file_conn(repo, "src", tmp_path / "a.csv", "id\n1\n")
    tgt_id = _file_conn(repo, "tgt", tmp_path / "b.csv", "id\n1\n")

    result = service.execute(
        FileChecksumRequest(source_connection_id=src_id, target_connection_id=tgt_id)
    )

    fetched = run_repo.get_by_id(result.run.run_id)
    assert fetched is not None
    assert fetched.summary["match"] is True
