"""Unit tests — ProjectService."""

from __future__ import annotations

import pytest

from datarecon.application.services.project_service import DEFAULT_PROJECT_ID, ProjectService


@pytest.fixture
def service(project_repository) -> ProjectService:
    return ProjectService(project_repository)


def test_create_project(service: ProjectService) -> None:
    project = service.create_project("Migration Q1", "ERP migration checks")
    assert project.name == "Migration Q1"
    assert service.get_project(project.project_id) is not None


def test_create_project_requires_name(service: ProjectService) -> None:
    with pytest.raises(ValueError, match="required"):
        service.create_project("   ")


def test_create_project_rejects_duplicate_name(service: ProjectService) -> None:
    service.create_project("Warehouse")
    with pytest.raises(ValueError, match="already exists"):
        service.create_project("Warehouse")


def test_update_project(service: ProjectService) -> None:
    project = service.create_project("Old Name")
    project.name = "New Name"
    updated = service.update_project(project)
    assert updated.name == "New Name"


def test_delete_project(service: ProjectService) -> None:
    project = service.create_project("Temp")
    assert service.delete_project(project.project_id) is True
    assert service.get_project(project.project_id) is None


def test_cannot_delete_default_project(service: ProjectService) -> None:
    with pytest.raises(ValueError, match="Default project"):
        service.delete_project(DEFAULT_PROJECT_ID)


def test_list_projects_includes_default(service: ProjectService) -> None:
    names = [p.name for p in service.list_projects()]
    assert "Default" in names
