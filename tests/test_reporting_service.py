"""Unit tests — ReportingService (Module 18)."""

from __future__ import annotations

import json

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


def test_csv_export_rejects_multi_section(service: ReportingService) -> None:
    payload = ReportPayload(
        title="x",
        summary={},
        sections=(
            ReportSection("A", pd.DataFrame({"a": [1]})),
            ReportSection("B", pd.DataFrame({"b": [2]})),
        ),
    )
    with pytest.raises(ReportingError, match="exactly one"):
        service.export(payload, ReportFormat.CSV)


def test_csv_export_rejects_zero_sections(service: ReportingService) -> None:
    payload = ReportPayload(title="x", summary={"a": 1})
    with pytest.raises(ReportingError, match="exactly one"):
        service.export(payload, ReportFormat.CSV)


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


def test_content_type_and_extension_mapping(service: ReportingService) -> None:
    assert service.file_extension(ReportFormat.EXCEL) == "xlsx"
    assert service.file_extension(ReportFormat.CSV) == "csv"
    assert service.content_type(ReportFormat.JSON) == "application/json"
