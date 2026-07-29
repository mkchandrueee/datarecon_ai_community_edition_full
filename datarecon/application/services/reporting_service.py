# datarecon/application/services/reporting_service.py
# Module 18: Reporting Engine (Community Edition scope — see ADR-0002:
# no white-label branded templates or scheduled distribution, those are
# Enterprise-only).
#
# Every validation module produces a summary dict plus zero or more
# DataFrames; ReportingService turns that generic shape into Excel/CSV/
# PDF/JSON bytes so the Streamlit view has one export code path instead
# of one per module.
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pandas as pd

from datarecon.domain.enums import ReportFormat

_PDF_MAX_ROWS_PER_SECTION = 500


class ReportingError(ValueError):
    """Raised for malformed or unsupported report requests."""


@dataclass(frozen=True)
class ReportSection:
    title: str
    dataframe: pd.DataFrame


@dataclass(frozen=True)
class ReportPayload:
    title: str
    summary: dict[str, Any]
    sections: Sequence[ReportSection] = field(default_factory=tuple)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ReportingService:
    def export(self, payload: ReportPayload, fmt: ReportFormat) -> bytes:
        if fmt == ReportFormat.EXCEL:
            return self._to_excel(payload)
        if fmt == ReportFormat.CSV:
            return self._to_csv(payload)
        if fmt == ReportFormat.PDF:
            return self._to_pdf(payload)
        if fmt == ReportFormat.JSON:
            return self._to_json(payload)
        raise ReportingError(f"Unsupported report format: {fmt}")

    @staticmethod
    def content_type(fmt: ReportFormat) -> str:
        return {
            ReportFormat.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ReportFormat.CSV: "text/csv",
            ReportFormat.PDF: "application/pdf",
            ReportFormat.JSON: "application/json",
        }[fmt]

    @staticmethod
    def file_extension(fmt: ReportFormat) -> str:
        return {"excel": "xlsx", "csv": "csv", "pdf": "pdf", "json": "json"}[fmt.value]

    # ------------------------------------------------------------------ #
    def _to_excel(self, payload: ReportPayload) -> bytes:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            summary_df = pd.DataFrame(
                {"metric": list(payload.summary.keys()), "value": list(payload.summary.values())}
            )
            summary_df.to_excel(writer, sheet_name="Summary", index=False)
            used_names: set[str] = {"Summary"}
            for section in payload.sections:
                sheet_name = self._unique_sheet_name(section.title, used_names)
                section.dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
        return buf.getvalue()

    @staticmethod
    def _unique_sheet_name(title: str, used: set[str]) -> str:
        base = "".join(c for c in title if c not in "[]:*?/\\")[:31] or "Sheet"
        name, i = base, 1
        while name in used:
            suffix = f"_{i}"
            name = base[: 31 - len(suffix)] + suffix
            i += 1
        used.add(name)
        return name

    def _to_csv(self, payload: ReportPayload) -> bytes:
        if len(payload.sections) != 1:
            raise ReportingError(
                f"CSV export requires exactly one data section, got {len(payload.sections)}. "
                "Use Excel or JSON for multi-section reports."
            )
        return payload.sections[0].dataframe.to_csv(index=False).encode("utf-8")

    def _to_json(self, payload: ReportPayload) -> bytes:
        doc = {
            "title": payload.title,
            "generated_at": payload.generated_at.isoformat(),
            "summary": payload.summary,
            "sections": {s.title: s.dataframe.to_dict(orient="records") for s in payload.sections},
        }
        return json.dumps(doc, default=str, indent=2).encode("utf-8")

    def _to_pdf(self, payload: ReportPayload) -> bytes:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(payload.title, styles["Title"]),
            Paragraph(f"Generated: {payload.generated_at.isoformat()}", styles["Normal"]),
            Spacer(1, 12),
            Paragraph("Summary", styles["Heading2"]),
            self._pdf_table([[str(k), str(v)] for k, v in payload.summary.items()]),
            Spacer(1, 12),
        ]
        for section in payload.sections:
            story.append(Paragraph(section.title, styles["Heading2"]))
            df = section.dataframe
            truncated = len(df) > _PDF_MAX_ROWS_PER_SECTION
            rows = df.head(_PDF_MAX_ROWS_PER_SECTION)
            data = [list(rows.columns), *rows.astype(str).values.tolist()]
            story.append(self._pdf_table(data, header=True))
            if truncated:
                story.append(
                    Paragraph(
                        f"Showing first {_PDF_MAX_ROWS_PER_SECTION} of {len(df)} rows.",
                        styles["Italic"],
                    )
                )
            story.append(Spacer(1, 12))
        doc.build(story)
        return buf.getvalue()

    @staticmethod
    def _pdf_table(data: list[list[str]], header: bool = False) -> Any:
        from reportlab.lib import colors
        from reportlab.platypus import Table, TableStyle

        if not data:
            data = [[""]]
        table = Table(data, repeatRows=1 if header else 0)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey))
        table.setStyle(TableStyle(style))
        return table
