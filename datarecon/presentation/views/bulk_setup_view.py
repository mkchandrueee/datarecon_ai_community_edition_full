# datarecon/presentation/views/bulk_setup_view.py — Bulk Setup
#
# Standing up validations for a whole schema one table at a time is the most
# tedious part of onboarding a new reconciliation: four modules across N tables of
# identical form-filling. This page takes a list of table names, generates the
# SQL for each module from the catalog (ADR-0011), and saves the lot as
# re-runnable Test Suites in one action.
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.duplicate_validation_service import (
    DuplicateValidationRequest,
)
from datarecon.application.services.nullability_validation_service import (
    NullabilityValidationRequest,
)
from datarecon.application.services.record_count_service import RecordCountRequest
from datarecon.application.services.schema_validation_service import SchemaValidationRequest
from datarecon.application.services.sql_generation_service import (
    SUPPORTED_MODULES,
    GeneratedSQL,
    TableGeneration,
)
from datarecon.application.services.test_suite_service import serialize_request
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.container import ServiceContainer

_RESULTS_KEY = "bulk_results"
_TARGET_KEY = "bulk_target_connection"

#: Modules needing a target to compare against; the rest profile one side only.
_TWO_SIDED = frozenset({ValidationModule.SCHEMA, ValidationModule.RECORD_COUNT})


def render(container: ServiceContainer) -> None:
    st.header("Bulk Setup")
    st.caption(
        "Generate validation SQL for many tables at once and save them as Test Suites. "
        "SQL is read from each table's catalog, so it can only reference real columns."
    )

    connections = container.connection_service.list_connections()
    projects = container.project_service.list_projects()
    if not projects:
        st.info("Create a Project first — bulk-generated suites are saved under one.")
        return

    col1, col2 = st.columns(2)
    with col1:
        source_id = connection_picker("Source Connection", connections, key="bulk_source")
    with col2:
        target_id = connection_picker("Target Connection", connections, key=_TARGET_KEY)

    project_name = st.selectbox("Save suites under project", [p.name for p in projects])
    project = next(p for p in projects if p.name == project_name)

    module_names = st.multiselect(
        "Modules",
        [m.value for m in SUPPORTED_MODULES],
        default=[m.value for m in SUPPORTED_MODULES],
        help="Schema and Record Count compare source against target; "
        "Duplicate and Nullability examine the source only.",
    )
    modules = tuple(ValidationModule(name) for name in module_names)

    tables_raw = st.text_area(
        "Tables",
        key="bulk_tables",
        height=140,
        placeholder="CUSTOMER_MASTER, ORDER_HEADER\nORDER_LINE",
        help="Separate with commas, semicolons or new lines.",
    )
    tables = container.sql_generation_service.parse_table_list(tables_raw)
    if tables:
        st.caption(f"{len(tables)} table(s) recognised.")

    if st.button(
        "✨ AI Generate SQL",
        type="primary",
        disabled=not (source_id and tables and modules),
    ):
        with st.spinner(f"Reading metadata for {len(tables)} table(s)..."):
            st.session_state[_RESULTS_KEY] = container.sql_generation_service.generate_bulk(
                source_id, tables, modules
            )

    results: list[TableGeneration] | None = st.session_state.get(_RESULTS_KEY)
    if not results:
        return

    _render_results(results)
    _render_suite_creation(container, results, project, source_id, target_id, modules)


def _render_results(results: list[TableGeneration]) -> None:
    succeeded = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]

    st.subheader("Generated SQL")
    c1, c2, c3 = st.columns(3)
    c1.metric("Tables", len(results))
    c2.metric("Generated", len(succeeded))
    c3.metric("Failed", len(failed))

    if failed:
        # A table that can't be introspected is worth naming rather than
        # silently dropping — usually a typo or a view without a catalog entry.
        st.warning("These tables could not be read:")
        st.dataframe(
            pd.DataFrame([{"Table": r.table, "Reason": r.error} for r in failed]),
            use_container_width=True,
            hide_index=True,
        )

    for result in succeeded:
        with st.expander(f"{result.table} — {len(result.statements)} statement(s)"):
            for statement in result.statements:
                st.markdown(f"**{statement.module.value}**")
                st.code(statement.sql, language="sql")
                st.caption(statement.note)


def _render_suite_creation(
    container: ServiceContainer,
    results: list[TableGeneration],
    project,
    source_id: str | None,
    target_id: str | None,
    modules: tuple[ValidationModule, ...],
) -> None:
    succeeded = [r for r in results if r.ok]
    if not succeeded or source_id is None:
        return

    needs_target = any(m in _TWO_SIDED for m in modules)
    st.subheader("Save as Test Suites")
    if needs_target and target_id is None:
        st.warning("Schema and Record Count need a target connection to compare against.")
        return

    planned = sum(len(r.statements) for r in succeeded)
    st.caption(
        f"{planned} suite(s) will be created — one per table per module, named with "
        "each module's code (e.g. RC_CUSTOMER_MASTER)."
    )

    if not st.button(f"Create {planned} Test Suite(s)", type="primary"):
        return

    created, errors = 0, []
    for result in succeeded:
        for statement in result.statements:
            try:
                request = _build_request(statement, result.table, source_id, target_id)
                container.test_suite_service.save_suite(
                    project_id=project.project_id,
                    name=result.table,
                    module=statement.module,
                    config=serialize_request(request),
                    description=f"Auto-generated from {result.table}",
                    source_connection_id=source_id,
                    target_connection_id=target_id
                    if statement.module in _TWO_SIDED
                    else None,
                )
                created += 1
            except Exception as exc:
                errors.append(f"{result.table} / {statement.module.value}: {exc}")

    if created:
        st.success(f"Created {created} test suite(s) under '{project.name}'.")
    for message in errors:
        st.error(message)


def _build_request(
    statement: GeneratedSQL, table: str, source_id: str, target_id: str | None
):
    """Build the module's Request from the generated SQL.

    The generated SQL goes in as the custom query on both sides: the two tables
    are assumed to share a name across source and target, which is the norm for
    a migration or replication check and is what a bulk run is for.
    """
    module = statement.module
    if module == ValidationModule.SCHEMA:
        return SchemaValidationRequest(
            source_connection_id=source_id,
            target_connection_id=target_id or "",
            source_query=statement.sql,
            target_query=statement.sql,
            name=table,
        )
    if module == ValidationModule.RECORD_COUNT:
        return RecordCountRequest(
            source_connection_id=source_id,
            target_connection_id=target_id or "",
            source_query=statement.sql,
            target_query=statement.sql,
            name=table,
        )
    if module == ValidationModule.DUPLICATE:
        return DuplicateValidationRequest(
            connection_id=source_id,
            key_columns=statement.suggested_keys,
            query=statement.sql,
            name=table,
        )
    return NullabilityValidationRequest(
        connection_id=source_id,
        columns=statement.suggested_columns,
        query=statement.sql,
        name=table,
    )
