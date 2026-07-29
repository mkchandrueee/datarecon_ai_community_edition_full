# datarecon/presentation/views/projects_view.py — Projects (Test Suite grouping)
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.project_service import DEFAULT_PROJECT_ID
from datarecon.presentation.container import ServiceContainer


def render(container: ServiceContainer) -> None:
    st.header("Projects")
    st.caption("Group related Test Suites by project — e.g. one project per source system or migration.")

    with st.expander("New Project"):
        name = st.text_input("Project Name", key="proj_new_name")
        description = st.text_area("Description (optional)", key="proj_new_description")
        if st.button("Create Project", type="primary", key="proj_new_create"):
            try:
                container.project_service.create_project(name, description)
                st.success(f"Project '{name}' created.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    projects = container.project_service.list_projects()
    if not projects:
        st.info("No projects yet.")
        return

    suites_by_project = {
        p.project_id: len(container.test_suite_service.list_suites(p.project_id)) for p in projects
    }
    table = pd.DataFrame(
        [
            {
                "name": p.name,
                "description": p.description,
                "test_suites": suites_by_project[p.project_id],
                "created_at": p.created_at,
            }
            for p in projects
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.subheader("Manage a Project")
    selected_name = st.selectbox(
        "Project", [p.name for p in projects], key="proj_manage_select"
    )
    project = next(p for p in projects if p.name == selected_name)

    with st.form("proj_edit_form"):
        new_name = st.text_input("Name", value=project.name)
        new_description = st.text_area("Description", value=project.description)
        col1, col2 = st.columns(2)
        save_clicked = col1.form_submit_button("Save Changes")
        delete_clicked = col2.form_submit_button(
            "Delete Project", disabled=project.project_id == DEFAULT_PROJECT_ID
        )

    if save_clicked:
        project.name = new_name
        project.description = new_description
        try:
            container.project_service.update_project(project)
            st.success("Project updated.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if delete_clicked:
        if suites_by_project[project.project_id]:
            st.error(
                "This project still has Test Suites. Delete them first, or move them "
                "to another project."
            )
        else:
            container.project_service.delete_project(project.project_id)
            st.success(f"Project '{project.name}' deleted.")
            st.rerun()
