"""Unit tests — ReportingService (Module 18)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from datarecon.application.services.reporting_service import (
    ReportingError,
    ReportingService,
    ReportPayload,
    ReportSection,
)
from datarecon.domain.enums import ReportFormat


@pytest.fixture
def service() -> ReportingService:
    return ReportingService()


@pytest.fixture
def payload() -> ReportPayload:
    return ReportPayload(
        title="Record Count Validation",
        summary={"source_count": 100, "target_count": 95, "status": "FAIL"},
        sections=(
            ReportSection(
                "Group Breakdown",
                pd.DataFrame({"region": ["east", "west"], "difference": [-3, -2]}),
            ),
        ),
    )


def test_json_export_roundtrips(service: ReportingService, payload: ReportPayload) -> None:
    raw = service.export(payload, ReportFormat.JSON)
    doc = json.loads(raw)
    assert doc["title"] == "Record Count Validation"
    assert doc["summary"]["source_count"] == 100
    assert doc["sections"]["Group Breakdown"][0]["region"] == "east"


def test_csv_export_single_section(service: ReportingService, payload: ReportPayload) -> None:
    raw = service.export(payload, ReportFormat.CSV)
    text = raw.decode("utf-8")
    assert "region,difference" in text
    assert "east,-3" in text


def test_csv_export_stacks_multiple_sections_under_banners(service: ReportingService) -> None:
    payload = ReportPayload(
        title="x",
        summary={"rows": 3},
        sections=(
            ReportSection("A", pd.DataFrame({"a": [1]})),
            ReportSection("B", pd.DataFrame({"b": [2]})),
        ),
    )
    text = service.export(payload, ReportFormat.CSV).decode("utf-8")
    assert "# Summary" in text
    assert "rows,3" in text
    assert "# A" in text
    assert "a\n1" in text
    assert "# B" in text
    assert "b\n2" in text


def test_csv_export_falls_back_to_summary_when_no_sections(service: ReportingService) -> None:
    payload = ReportPayload(title="x", summary={"source_count": 10, "target_count": 10})
    text = service.export(payload, ReportFormat.CSV).decode("utf-8")
    assert "metric,value" in text
    assert "source_count,10" in text
    assert "target_count,10" in text


def test_csv_line_endings_are_lf_on_every_platform(service: ReportingService) -> None:
    """Pinned so a report built on Windows matches one built on Linux, and the
    banner lines never mix with pandas' CRLF inside a single file."""
    payload = ReportPayload(
        title="x",
        summary={"rows": 1},
        sections=(
            ReportSection("A", pd.DataFrame({"a": [1]})),
            ReportSection("B", pd.DataFrame({"b": [2]})),
        ),
    )
    for shape in (payload, ReportPayload(title="x", summary={"rows": 1})):
        assert b"\r\n" not in service.export(shape, ReportFormat.CSV)


def test_csv_export_of_empty_section_still_emits_header(service: ReportingService) -> None:
    payload = ReportPayload(
        title="x",
        summary={},
        sections=(ReportSection("Mismatches", pd.DataFrame(columns=["id", "email"])),),
    )
    text = service.export(payload, ReportFormat.CSV).decode("utf-8")
    assert "id,email" in text


def test_excel_export_produces_nonempty_workbook(
    service: ReportingService, payload: ReportPayload
) -> None:
    raw = service.export(payload, ReportFormat.EXCEL)
    assert raw[:2] == b"PK"  # xlsx is a zip archive
    assert len(raw) > 100


def test_excel_export_handles_many_sections_and_long_titles(service: ReportingService) -> None:
    sections = tuple(
        ReportSection(f"Section With A Very Long Title Number {i}", pd.DataFrame({"x": [i]}))
        for i in range(5)
    )
    payload = ReportPayload(title="stress", summary={"n": 5}, sections=sections)
    raw = service.export(payload, ReportFormat.EXCEL)
    assert raw[:2] == b"PK"


def test_pdf_export_produces_pdf_bytes(service: ReportingService, payload: ReportPayload) -> None:
    raw = service.export(payload, ReportFormat.PDF)
    assert raw[:4] == b"%PDF"


def test_pdf_export_handles_empty_sections(service: ReportingService) -> None:
    payload = ReportPayload(title="empty", summary={"n": 0}, sections=())
    raw = service.export(payload, ReportFormat.PDF)
    assert raw[:4] == b"%PDF"


def test_unsupported_format_raises(service: ReportingService, payload: ReportPayload) -> None:
    with pytest.raises(ReportingError, match="Unsupported report format"):
        service.export(payload, "xml")  # type: ignore[arg-type]


def test_content_type_and_extension_mapping(service: ReportingService) -> None:
    assert service.file_extension(ReportFormat.EXCEL) == "xlsx"
    assert service.file_extension(ReportFormat.CSV) == "csv"
    assert service.content_type(ReportFormat.JSON) == "application/json"


# ---------- Excel and timezone-aware timestamps ----------


def test_excel_export_handles_tz_aware_datetime_column(service: ReportingService) -> None:
    """xlsx has no tz-aware datetime type; xlsxwriter raises rather than guess."""
    table = pd.DataFrame(
        {"run": ["a", "b"], "started_at": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True)}
    )
    payload = ReportPayload(title="x", summary={}, sections=(ReportSection("Runs", table),))

    raw = service.export(payload, ReportFormat.EXCEL)

    assert raw[:2] == b"PK"


def test_excel_export_handles_object_column_of_tz_aware_values(
    service: ReportingService,
) -> None:
    """Datetimes mixed with None stay object-dtype, so .dt is unavailable."""
    table = pd.DataFrame(
        {"suite": ["a", "b"], "last_run": [datetime(2026, 1, 1, tzinfo=UTC), None]}
    )
    payload = ReportPayload(title="x", summary={}, sections=(ReportSection("Suites", table),))

    raw = service.export(payload, ReportFormat.EXCEL)

    assert raw[:2] == b"PK"


def test_excel_export_handles_tz_aware_value_in_summary(service: ReportingService) -> None:
    payload = ReportPayload(title="x", summary={"generated": datetime(2026, 1, 1, tzinfo=UTC)})

    raw = service.export(payload, ReportFormat.EXCEL)

    assert raw[:2] == b"PK"


def test_excel_safe_leaves_naive_frames_untouched(service: ReportingService) -> None:
    table = pd.DataFrame({"a": [1], "when": pd.to_datetime(["2026-01-01"])})
    assert service._excel_safe(table) is table
