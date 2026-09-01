# datarecon/presentation/views/referential_integrity_view.py — Referential Integrity
#
# Child rows whose foreign key has no matching parent (orphans). The child and
# parent may sit on different connections, which is the point: the check is
# most valuable exactly where the database can't enforce it itself — across a
# migration, a replication boundary, or a warehouse that dropped its FKs.
from __future__ import annotations

import streamlit as st

from datarecon.application.services.referential_integrity_service import (
    ReferentialIntegrityRequest,
)
from datarecon.application.services.reporting_service import (
    ReportPayload,
    ReportSection,
    sanitize_export_name,
)
from datarecon.application.services.test_suite_service import prefixed_name, serialize_request
from datarecon.domain.enums import ValidationModule
from datarecon.presentation.components.connection_picker import connection_picker
from datarecon.presentation.components.extraction_inputs import (
    extraction_inputs,
    stage_table,
)
from datarecon.presentation.components.report_export import (
    render_detail_csv_downloads,
    render_export_buttons,
)
from datarecon.presentation.components.run_status import render_status_badge
from datarecon.presentation.components.test_suite_save import render_save_suite_section
from datarecon.presentation.container import ServiceContainer

_FK_KEY = "ri_detected_fks"

#: Rows rendered on screen; the full extract is in the downloads below.
_MAX_DISPLAY_ROWS = 5_000


def render(container: ServiceContainer) -> None:
    st.header("Referential Integrity")
    st.caption(
        "Finds child rows whose foreign key has no matching parent. "
        "Rows with a NULL key are not orphans — they simply reference nothing."
    )
    connections = container.connection_service.list_connections()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Child (referencing)")
        child_id = connection_picker("Child Connection", connections, key="ri_child")
        child_query, child_table = extraction_inputs("Child", "ri_child")
    with col2:
        st.subheader("Parent (referenced)")
        parent_id = connection_picker("Parent Connection", connections, key="ri_parent")
        parent_query, parent_table = extraction_inputs("Parent", "ri_parent")

    _render_fk_detection(container, child_id, child_table)

    kcol1, kcol2 = st.columns(2)
    child_keys_raw = kcol1.text_input(
        "Child Key Column(s), comma-separated", key="ri_child_keys"
    )
    parent_keys_raw = kcol2.text_input(
        "Parent Key Column(s), comma-separated", key="ri_parent_keys"
    )
    st.caption("Columns pair up in order, so composite keys must list in the same order.")

    ocol1, ocol2 = st.columns(2)
    tolerance = ocol1.number_input(
        "Orphan tolerance (%)", min_value=0.0, max_value=100.0, value=0.0, key="ri_tolerance"
    )
    sample_limit = ocol2.number_input(
        "Sample Limit", min_value=10, max_value=100_000, value=1000, key="ri_limit"
    )

    child_keys = [c.strip() for c in child_keys_raw.split(",") if c.strip()]
    parent_keys = [c.strip() for c in parent_keys_raw.split(",") if c.strip()]
    # A parent key list left blank means "same names as the child", which is
    # the overwhelmingly common case and saves retyping.
    effective_parent_keys = parent_keys or child_keys

    request = ReferentialIntegrityRequest(
        child_connection_id=child_id or "",
        child_columns=child_keys,
        parent_connection_id=parent_id or "",
        parent_columns=effective_parent_keys,
        child_query=child_query,
        child_table=child_table,
        parent_query=parent_query,
        parent_table=parent_table,
        tolerance_percent=float(tolerance),
        sample_limit=int(sample_limit),
    )
    if child_id and parent_id:
        render_save_suite_section(
            container,
            ValidationModule.REFERENTIAL_INTEGRITY,
            serialize_request(request),
            key_prefix="ri",
            source_connection_id=child_id,
            target_connection_id=parent_id,
        )

    if st.button(
        "Run Referential Integrity", type="primary", disabled=not (child_id and parent_id)
    ):
        if not child_keys:
            st.warning("At least one child key column is required.")
            return
        try:
            with st.spinner("Checking for orphan rows..."):
                result = container.referential_integrity_service.execute(request)
        except Exception as exc:
            st.error(f"Referential integrity check failed: {exc}")
            return

        render_status_badge(result.status, result.run.runtime_seconds)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Child Rows", f"{result.child_rows:,}")
        c2.metric("Checked", f"{result.checked_rows:,}", help="Rows with a non-null key")
        c3.metric("Orphans", f"{result.orphan_rows:,}")
        c4.metric("Orphan %", f"{result.orphan_percent:.4f}")
        if result.null_key_rows:
            st.caption(
                f"{result.null_key_rows:,} row(s) had a NULL key and were not checked — "
                "a NULL foreign key references nothing rather than something missing."
            )

        st.subheader("Orphan Rows")
        if result.orphans.empty:
            st.success("No orphans — every child key has a matching parent.")
        else:
            st.caption(
                f"{result.distinct_orphan_keys:,} distinct unmatched key value(s)."
            )
            st.dataframe(
                result.orphans.head(_MAX_DISPLAY_ROWS), use_container_width=True, hide_index=True
            )
            if len(result.orphans) > _MAX_DISPLAY_ROWS:
                st.caption(
                    f"Previewing the first {_MAX_DISPLAY_ROWS:,} of "
                    f"{len(result.orphans):,} rows. All rows are in the download(s) below."
                )
        render_detail_csv_downloads(
            container.reporting_service,
            sanitize_export_name(
                prefixed_name(ValidationModule.REFERENTIAL_INTEGRITY, result.run.name)
            )
            + "_Orphans",
            result.orphans,
            key="ri_dl_orphans",
            label="Download orphans CSV",
        )

        st.divider()
        payload = ReportPayload(
            title="Referential Integrity",
            summary=result.run.summary,
            sections=(ReportSection("Orphan Rows", result.orphans),),
        )
        render_export_buttons(container.reporting_service, payload, key_prefix="ri")


def _render_fk_detection(
    container: ServiceContainer, child_id: str | None, child_table: str | None
) -> None:
    """Offer the foreign keys the database already declares, so the usual case
    needs no typing. Absence of a declared FK is not absence of a relationship,
    which is why the fields stay editable."""
    if not (child_id and child_table):
        return

    if st.button("Detect foreign keys", key="ri_detect_fks", use_container_width=True):
        foreign_keys = container.extraction_service.get_foreign_keys(child_id, child_table)
        st.session_state[_FK_KEY] = (child_table, foreign_keys)

    detected = st.session_state.get(_FK_KEY)
    if not detected or detected[0].casefold() != child_table.casefold():
        return

    _, foreign_keys = detected
    if foreign_keys is None:
        st.caption("Foreign keys can't be read for this connection type.")
        return
    if not foreign_keys:
        st.caption("No foreign keys declared on this table — enter the columns manually.")
        return

    labels = [fk.label(child_table) for fk in foreign_keys]
    chosen = st.selectbox("Detected relationships", labels, key="ri_fk_choice")
    fk = foreign_keys[labels.index(chosen)]
    if st.button("Use this relationship", key="ri_fk_apply"):
        st.session_state["ri_child_keys"] = ", ".join(fk.columns)
        st.session_state["ri_parent_keys"] = ", ".join(fk.referred_columns)
        # The parent Table Name box already exists on this run, so the value is
        # staged and applied by extraction_inputs() before it is next created.
        stage_table("ri_parent", fk.qualified_parent)
        st.rerun()
