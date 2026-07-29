"""Unit tests — SQLiteProjectRepository."""

from __future__ import annotations

from datarecon.domain.entities.project import Project
from datarecon.infrastructure.persistence.sqlite_project_repository import (
    SQLiteProjectRepository,
)


def test_default_project_seeded(project_repository: SQLiteProjectRepository) -> None:
    default = project_repository.get_by_id("default")
    assert default is not None
    assert default.name == "Default"


def test_add_and_get_roundtrip(project_repository: SQLiteProjectRepository) -> None:
    project = Project(name="Migration Q1", description="ERP migration checks")
    project_repository.add(project)

    fetched = project_repository.get_by_id(project.project_id)
    assert fetched is not None
    assert fetched.name == "Migration Q1"
    assert fetched.description == "ERP migration checks"


def test_get_by_name(project_repository: SQLiteProjectRepository) -> None:
    project_repository.add(Project(name="Warehouse"))
    fetched = project_repository.get_by_name("Warehouse")
    assert fetched is not None
    assert fetched.name == "Warehouse"
    assert project_repository.get_by_name("does-not-exist") is None


def test_update(project_repository: SQLiteProjectRepository) -> None:
    project = project_repository.add(Project(name="Old Name"))
    project.name = "New Name"
    project.description = "updated"
    project_repository.update(project)

    fetched = project_repository.get_by_id(project.project_id)
    assert fetched is not None
    assert fetched.name == "New Name"
    assert fetched.description == "updated"


def test_delete(project_repository: SQLiteProjectRepository) -> None:
    project = project_repository.add(Project(name="Temp"))
    assert project_repository.delete(project.project_id) is True
    assert project_repository.get_by_id(project.project_id) is None
    assert project_repository.delete(project.project_id) is False


def test_list_all_ordered_by_name(project_repository: SQLiteProjectRepository) -> None:
    project_repository.add(Project(name="Zebra"))
    project_repository.add(Project(name="Alpha"))
    names = [p.name for p in project_repository.list_all()]
    assert names == sorted(names)
    assert "Alpha" in names and "Zebra" in names
