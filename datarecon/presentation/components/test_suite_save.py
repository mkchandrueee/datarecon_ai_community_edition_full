# datarecon/presentation/components/test_suite_save.py
# Shared "Save as Test Suite" widget used by every runnable validation
# module view, so a configured comparison can be re-run later for
# regression checks (ADR-0005) without re-entering the same parameters.
from __future__ import annotations

from typing import Any

import streamlit as st

from datarecon.application.services.test_suite_service import prefixed_name
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.container import ServiceContainer


def render_save_suite_section(
    container: ServiceContainer,
    module: ValidationModule,
    config: dict[str, Any],
    key_prefix: str,
    source_connection_id: str | None = None,
    target_connection_id: str | None = None,
) -> None:
    """Render an expander that saves the current form configuration as a
    named Test Suite under a chosen Project."""
    projects = container.project_service.list_projects()
    with st.expander("💾 Save as Test Suite"):
        if not projects:
            st.caption("No projects yet — create one on the Projects page first.")
            return
        project_names = [p.name for p in projects]
        project_choice = st.selectbox(
            "Project", project_names, key=f"{key_prefix}_suite_project"
        )
        suite_name = st.text_input("Test Suite Name", key=f"{key_prefix}_suite_name")
        if suite_name.strip():
            st.caption(f"Will be saved as **{prefixed_name(module, suite_name)}**")
        else:
            st.caption(f"Saved names are prefixed with `{module.code}_` for this module.")
        description = st.text_input(
            "Description (optional)", key=f"{key_prefix}_suite_description"
        )
        if st.button("Save Test Suite", key=f"{key_prefix}_suite_save"):
            if not suite_name.strip():
                st.warning("Test suite name is required.")
                return
            project = next(p for p in projects if p.name == project_choice)
            try:
                saved = container.test_suite_service.save_suite(
                    project_id=project.project_id,
                    name=suite_name,
                    module=module,
                    config=config,
                    description=description,
                    source_connection_id=source_connection_id,
                    target_connection_id=target_connection_id,
                )
                st.success(f"Saved test suite '{saved.name}' under project '{project.name}'.")
            except ValueError as exc:
                st.error(str(exc))
