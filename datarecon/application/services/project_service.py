# datarecon/application/services/project_service.py
# CRUD for Projects — the grouping unit for saved Test Suites (ADR-0005).
from __future__ import annotations

from datarecon.domain.entities.project import DEFAULT_PROJECT_ID, Project
from datarecon.domain.interfaces.project_repository import IProjectRepository

__all__ = ["DEFAULT_PROJECT_ID", "ProjectService"]


class ProjectService:
    def __init__(self, repository: IProjectRepository):
        self._repo = repository

    def list_projects(self) -> list[Project]:
        return self._repo.list_all()

    def get_project(self, project_id: str) -> Project | None:
        return self._repo.get_by_id(project_id)

    def create_project(self, name: str, description: str = "") -> Project:
        name = name.strip()
        if not name:
            raise ValueError("Project name is required.")
        if self._repo.get_by_name(name):
            raise ValueError(f"A project named '{name}' already exists.")
        return self._repo.add(Project(name=name, description=description))

    def update_project(self, project: Project) -> Project:
        if not project.name.strip():
            raise ValueError("Project name is required.")
        return self._repo.update(project)

    def delete_project(self, project_id: str) -> bool:
        if project_id == DEFAULT_PROJECT_ID:
            raise ValueError("The Default project cannot be deleted.")
        return self._repo.delete(project_id)
