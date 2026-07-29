# datarecon/presentation/views/connections_view.py  (MODIFIED — category-driven form)
from __future__ import annotations

import pandas as pd
import streamlit as st

from datarecon.application.services.connection_service import ConnectionService
from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import (
    ConnectionCategory,
    ConnectionRole,
    DatabaseType,
    Environment,
    category_of,
)

_FORM_DEFAULT_PORTS = {
    DatabaseType.POSTGRESQL: 5432,
    DatabaseType.GREENPLUM: 5432,
    DatabaseType.MYSQL: 3306,
    DatabaseType.MARIADB: 3306,
    DatabaseType.SQLSERVER: 1433,
    DatabaseType.SYNAPSE: 1433,
    DatabaseType.AZURE_SQL: 1433,
    DatabaseType.ORACLE: 1521,
    DatabaseType.DB2: 50000,
    DatabaseType.TERADATA: 1025,
    DatabaseType.REDSHIFT: 5439,
    DatabaseType.DATABRICKS: 443,
    DatabaseType.HIVE: 10000,
    DatabaseType.SPARK: 10000,
    DatabaseType.SAP_HANA: 30015,
    DatabaseType.MONGODB: 27017,
    DatabaseType.INFORMIX: 9088,
}

_SECRET_LABELS = {
    DatabaseType.AWS_S3: "Secret Access Key",
    DatabaseType.AZURE_BLOB: "Account Key / SAS Token",
    DatabaseType.AZURE_DATA_LAKE: "Account Key / SAS Token",
    DatabaseType.GCS: "Service Account JSON",
    DatabaseType.DATABRICKS: "Personal Access Token",
}


def render(service: ConnectionService) -> None:
    st.header("Connection Management")
    tab_list, tab_create = st.tabs(["Connections", "Create / Edit"])
    with tab_list:
        _render_grid(service)
    with tab_create:
        edit_id = st.session_state.get("edit_connection_id")
        _render_form(service, service.get_connection(edit_id) if edit_id else None)


def _render_grid(service: ConnectionService) -> None:
    connections = service.list_connections()
    if not connections:
        st.info("No connections defined. Use the Create / Edit tab to add one.")
        return

    df = pd.DataFrame(
        [
            {
                "Name": c.connection_name,
                "Role": c.connection_role.value,
                "Category": c.category.value,
                "Type": c.database_type.value,
                "Project": c.project,
                "Env": c.environment.value,
                "Endpoint": c.host
                or c.account
                or c.bucket
                or c.file_path
                or c.jdbc_url
                or c.driver
                or "-",
                "Database": c.database_name or c.catalog or "-",
                "Last Test": c.last_test_status or "-",
                "Usage": c.usage_count,
            }
            for c in connections
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    options = {c.connection_name: c.connection_id for c in connections}
    selected = st.selectbox("Select connection", list(options))
    cid = options[selected]

    col_test, col_edit, col_clone, col_delete = st.columns(4)
    if col_test.button("Test Connectivity", use_container_width=True):
        with st.spinner("Testing..."):
            result = service.test_connection(cid)
        if result.success:
            st.success(f"PASS ({result.elapsed_ms} ms)")
        else:
            st.error(f"FAIL ({result.elapsed_ms} ms): {result.message}")

    if col_edit.button("Edit", use_container_width=True):
        st.session_state["edit_connection_id"] = cid
        st.rerun()

    if col_clone.button("Clone", use_container_width=True):
        clone = service.clone_connection(cid)
        st.success(f"Cloned as '{clone.connection_name}'.")
        st.rerun()

    if col_delete.button("Delete", type="primary", use_container_width=True):
        st.session_state["pending_delete_id"] = cid

    if st.session_state.get("pending_delete_id") == cid:
        st.warning(f"Delete connection '{selected}'? This cannot be undone.")
        c1, c2 = st.columns(2)
        if c1.button("Confirm Delete", type="primary"):
            service.delete_connection(cid)
            st.session_state.pop("pending_delete_id", None)
            st.rerun()
        if c2.button("Cancel"):
            st.session_state.pop("pending_delete_id", None)
            st.rerun()


def _v(existing: Connection | None, attr: str, default: str = "") -> str:
    return (getattr(existing, attr) or default) if existing else default


def _render_form(service: ConnectionService, existing: Connection | None) -> None:
    is_edit = existing is not None
    st.subheader("Edit Connection" if is_edit else "New Connection")

    db_type = st.selectbox(
        "Source Type",
        list(DatabaseType),
        format_func=lambda d: f"{d.value}  ·  {category_of(d).value}",
        index=list(DatabaseType).index(existing.database_type) if existing is not None else 0,
    )
    category = category_of(db_type)

    with st.form("connection_form", clear_on_submit=not is_edit):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Connection Name", value=_v(existing, "connection_name"))
            role = st.selectbox(
                "Connection Role",
                list(ConnectionRole),
                format_func=lambda r: r.value,
                index=list(ConnectionRole).index(existing.connection_role)
                if existing is not None
                else 0,
            )
            project = st.text_input("Project", value=_v(existing, "project", "Default"))
        with col2:
            environment = st.selectbox(
                "Environment",
                list(Environment),
                format_func=lambda e: e.value,
                index=list(Environment).index(existing.environment) if existing is not None else 0,
            )
            schema_name = st.text_input("Schema Name", value=_v(existing, "schema_name"))

        entity = (
            existing
            if existing is not None
            else Connection(connection_name="", connection_role=role, database_type=db_type)
        )
        password = ""
        pwd_help = "Leave blank to keep the existing credential." if is_edit else None

        # ---------- category-specific fields ----------
        if db_type == DatabaseType.SQLITE:
            entity.file_path = st.text_input("SQLite File Path", value=_v(existing, "file_path"))

        elif category == ConnectionCategory.FILE:
            entity.file_path = st.text_input("File Path", value=_v(existing, "file_path"))
            entity.extra_options = (
                st.text_input(
                    "Read Options (JSON)",
                    value=_v(existing, "extra_options"),
                    placeholder='{"delimiter": "|", "sheet_name": "Data"}',
                )
                or None
            )

        elif category == ConnectionCategory.STORAGE:
            c1, c2 = st.columns(2)
            entity.bucket = c1.text_input(
                "Bucket / Container / Filesystem", value=_v(existing, "bucket")
            )
            entity.file_path = c2.text_input("Default Object Path", value=_v(existing, "file_path"))
            if db_type == DatabaseType.AWS_S3:
                c3, c4 = st.columns(2)
                entity.username = c3.text_input("Access Key ID", value=_v(existing, "username"))
                entity.region = c4.text_input("Region", value=_v(existing, "region"))
            elif db_type in (DatabaseType.AZURE_BLOB, DatabaseType.AZURE_DATA_LAKE):
                entity.storage_account = st.text_input(
                    "Storage Account", value=_v(existing, "storage_account")
                )
            elif db_type == DatabaseType.GCS:
                entity.cloud_project = st.text_input(
                    "GCP Project", value=_v(existing, "cloud_project")
                )
            password = (
                st.text_area(
                    _SECRET_LABELS.get(db_type, "Secret"),
                    value="",
                    help=pwd_help,
                    height=68,
                )
                if db_type == DatabaseType.GCS
                else st.text_input(
                    _SECRET_LABELS.get(db_type, "Secret"),
                    type="password",
                    help=pwd_help,
                )
            )

        elif db_type == DatabaseType.MONGODB:
            c1, c2 = st.columns([3, 1])
            entity.host = c1.text_input("Host / SRV Host", value=_v(existing, "host"))
            entity.port = int(
                c2.number_input(
                    "Port",
                    1,
                    65535,
                    value=(existing.port if existing is not None and existing.port else 27017),
                )
            )
            entity.database_name = st.text_input("Database", value=_v(existing, "database_name"))
            entity.username = st.text_input("Username", value=_v(existing, "username"))
            password = st.text_input("Password", type="password", help=pwd_help)
            entity.extra_options = (
                st.text_input(
                    "Options (JSON)",
                    value=_v(existing, "extra_options"),
                    placeholder='{"srv": true, "auth_source": "admin"}',
                )
                or None
            )

        elif db_type == DatabaseType.JDBC or (
            db_type == DatabaseType.IDMS
            and st.checkbox("Connect via JDBC bridge", value=bool(_v(existing, "jdbc_url")))
        ):
            entity.jdbc_url = st.text_input("JDBC URL", value=_v(existing, "jdbc_url"))
            entity.driver_class = st.text_input("Driver Class", value=_v(existing, "driver_class"))
            entity.driver_location = st.text_input(
                "Driver Location (jar paths, comma-separated)",
                value=_v(existing, "driver_location"),
            )
            entity.username = st.text_input("Username", value=_v(existing, "username"))
            password = st.text_input("Password", type="password", help=pwd_help)

        elif db_type in (DatabaseType.ODBC, DatabaseType.INFORMIX, DatabaseType.IDMS):
            entity.driver = st.text_input("ODBC Driver Name or DSN", value=_v(existing, "driver"))
            c1, c2 = st.columns([3, 1])
            entity.host = (
                c1.text_input("Host (optional for DSN)", value=_v(existing, "host")) or None
            )
            port_val = c2.number_input(
                "Port",
                0,
                65535,
                value=(
                    existing.port
                    if existing is not None and existing.port
                    else _FORM_DEFAULT_PORTS.get(db_type, 0)
                ),
            )
            entity.port = int(port_val) or None
            entity.database_name = (
                st.text_input("Database", value=_v(existing, "database_name")) or None
            )
            entity.username = st.text_input("Username", value=_v(existing, "username")) or None
            password = st.text_input("Password", type="password", help=pwd_help)
            entity.extra_options = (
                st.text_input(
                    "Options (JSON)",
                    value=_v(existing, "extra_options"),
                    placeholder='{"server": "ol_informix", "connection_string": "..."}',
                )
                or None
            )

        elif db_type == DatabaseType.SNOWFLAKE:
            entity.account = st.text_input(
                "Account Identifier",
                value=_v(existing, "account"),
                placeholder="orgname-accountname",
            )
            c1, c2, c3 = st.columns(3)
            entity.database_name = c1.text_input("Database", value=_v(existing, "database_name"))
            entity.warehouse = c2.text_input("Warehouse", value=_v(existing, "warehouse"))
            entity.role = c3.text_input("Role", value=_v(existing, "role"))
            entity.username = st.text_input("Username", value=_v(existing, "username"))
            password = st.text_input("Password", type="password", help=pwd_help)

        elif db_type == DatabaseType.DATABRICKS:
            entity.host = st.text_input(
                "Workspace Host",
                value=_v(existing, "host"),
                placeholder="adb-xxxx.azuredatabricks.net",
            )
            entity.http_path = st.text_input("HTTP Path", value=_v(existing, "http_path"))
            c1, c2 = st.columns(2)
            entity.catalog = c1.text_input("Catalog", value=_v(existing, "catalog"))
            entity.database_name = c2.text_input(
                "Schema/Database", value=_v(existing, "database_name")
            )
            password = st.text_input(
                _SECRET_LABELS[DatabaseType.DATABRICKS], type="password", help=pwd_help
            )

        else:  # remaining network relational databases
            c1, c2 = st.columns([3, 1])
            entity.host = c1.text_input("Host Name", value=_v(existing, "host"))
            entity.port = int(
                c2.number_input(
                    "Port",
                    1,
                    65535,
                    value=(
                        existing.port
                        if existing is not None
                        and existing.port
                        and existing.database_type == db_type
                        else _FORM_DEFAULT_PORTS.get(db_type, 5432)
                    ),
                )
            )
            entity.database_name = st.text_input(
                "Database / Service Name", value=_v(existing, "database_name")
            )
            if db_type in (DatabaseType.SQLSERVER, DatabaseType.SYNAPSE, DatabaseType.AZURE_SQL):
                entity.driver = st.text_input(
                    "ODBC Driver",
                    value=_v(existing, "driver", "ODBC Driver 18 for SQL Server"),
                )
            entity.username = st.text_input("Username", value=_v(existing, "username"))
            password = st.text_input("Password", type="password", help=pwd_help)

        submitted = st.form_submit_button(
            "Save Changes" if is_edit else "Create Connection", type="primary"
        )

    if submitted:
        try:
            entity.connection_name = name.strip()
            entity.connection_role = role
            entity.database_type = db_type
            entity.project = project.strip() or "Default"
            entity.environment = environment
            entity.schema_name = schema_name or None

            if is_edit:
                service.update_connection(entity, password or None)
                st.session_state.pop("edit_connection_id", None)
                st.success("Connection updated.")
            else:
                service.create_connection(entity, password)
                st.success(f"Connection '{entity.connection_name}' created.")
            st.rerun()
        except ValueError as err:
            st.error(str(err))

    if is_edit and st.button("Cancel Edit"):
        st.session_state.pop("edit_connection_id", None)
        st.rerun()
