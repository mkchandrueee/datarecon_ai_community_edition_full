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
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pandas as pd

from datarecon.domain.enums import ReportFormat

_PDF_MAX_ROWS_PER_SECTION = 500

#: Rows per download batch for row-level extracts (ADR-0013). Half a million
#: mismatches in one CSV is a file most desktops open badly and some not at all;
#: 50k is the size a reviewer can actually work with in Excel.
DEFAULT_BATCH_ROWS = 50_000

#: xlsx caps a worksheet at 1,048,576 rows including the header, so a section
#: any larger has to span numbered sheets or the writer raises.
EXCEL_MAX_ROWS_PER_SHEET = 1_000_000

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class ReportingError(ValueError):
    """Raised for malformed or unsupported report requests."""


def sanitize_export_name(name: str) -> str:
    """Turn a section or run name into something safe for a download filename.

    Names reach here from user input (suite names, table names), so they can
    carry spaces, slashes and punctuation that browsers and file systems handle
    inconsistently. Runs of unsafe characters collapse to a single underscore.
    """
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip("_")
    return cleaned or "export"


def _drop_tz(value: Any) -> Any:
    tzinfo = getattr(value, "tzinfo", None)
    return value.replace(tzinfo=None) if tzinfo is not None else value


def _has_tz_aware_value(series: pd.Series) -> bool:
    return any(getattr(v, "tzinfo", None) is not None for v in series)


@dataclass(frozen=True)
class ReportSection:
    title: str
    dataframe: pd.DataFrame


@dataclass(frozen=True)
class ReportBatch:
    """One numbered slice of a row-level extract."""

    name: str
    number: int
    total: int
    #: 1-based inclusive row range within the full section; 0/0 when empty.
    first_row: int
    last_row: int
    dataframe: pd.DataFrame

    @property
    def is_only_batch(self) -> bool:
        return self.total == 1

    @property
    def row_range_label(self) -> str:
        if self.last_row == 0:
            return "no rows"
        return f"rows {self.first_row:,}-{self.last_row:,}"


@dataclass(frozen=True)
class ReportPayload:
    title: str
    summary: dict[str, Any]
    sections: Sequence[ReportSection] = field(default_factory=tuple)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ReportingService:
    _SUMMARY_TITLE = "Summary"

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
    @staticmethod
    def batch_frame(
        name: str, df: pd.DataFrame, batch_rows: int = DEFAULT_BATCH_ROWS
    ) -> list[ReportBatch]:
        """Split a row-level extract into numbered batches (ADR-0013).

        A section at or under the threshold comes back as a single batch under
        its own name, so nothing about small downloads changes. Above it, the
        section is sliced into `NAME_1`, `NAME_2`, … in row order, covering
        every row — batching is about file size, never about dropping rows.
        """
        if batch_rows < 1:
            raise ReportingError("batch_rows must be at least 1.")

        rows = len(df)
        if rows <= batch_rows:
            return [
                ReportBatch(
                    name=name,
                    number=1,
                    total=1,
                    first_row=1 if rows else 0,
                    last_row=rows,
                    dataframe=df,
                )
            ]

        total = -(-rows // batch_rows)  # ceiling division
        return [
            ReportBatch(
                name=f"{name}_{number}",
                number=number,
                total=total,
                first_row=start + 1,
                last_row=min(start + batch_rows, rows),
                dataframe=df.iloc[start : start + batch_rows],
            )
            for number, start in enumerate(range(0, rows, batch_rows), start=1)
        ]

    # ------------------------------------------------------------------ #
    def _to_excel(self, payload: ReportPayload) -> bytes:
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            self._excel_safe(self._summary_frame(payload)).to_excel(
                writer, sheet_name=self._SUMMARY_TITLE, index=False
            )
            used_names: set[str] = {self._SUMMARY_TITLE}
            for section in payload.sections:
                # A worksheet can't hold more than ~1M rows, so a section past
                # that spans numbered sheets rather than failing the export.
                for batch in self.batch_frame(
                    section.title, section.dataframe, EXCEL_MAX_ROWS_PER_SHEET
                ):
                    sheet_name = self._unique_sheet_name(batch.name, used_names)
                    self._excel_safe(batch.dataframe).to_excel(
                        writer, sheet_name=sheet_name, index=False
                    )
        return buf.getvalue()

    @staticmethod
    def _excel_safe(df: pd.DataFrame) -> pd.DataFrame:
        """Drop timezones from datetime columns.

        Run timestamps are stored tz-aware (UTC), but the xlsx format has no
        tz-aware datetime type and xlsxwriter raises rather than guessing.
        The instants are already UTC, so dropping the offset loses nothing a
        reader of the sheet would miss.
        """
        out = df
        for column in df.columns:
            series = df[column]
            if isinstance(series.dtype, pd.DatetimeTZDtype):
                converted = series.dt.tz_localize(None)
            elif series.dtype == object and _has_tz_aware_value(series):
                # A column of datetimes mixed with None stays object-dtype, so
                # the .dt accessor isn't available — strip per value instead.
                converted = series.map(_drop_tz)
            else:
                continue
            if out is df:
                out = df.copy()
            out[column] = converted
        return out

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
        """CSV for any payload shape. CSV is a single flat table, so a report
        with no data sections falls back to its summary metrics, and one with
        several stacks them under `# <section title>` banner lines — every
        module offers a working CSV download rather than a dead 'n/a' button.

        Line endings are pinned to \\n rather than the platform default, so a
        report generated on Windows is byte-identical to one from Linux and the
        banner lines can't end up mixed with pandas' CRLF inside one file."""
        if len(payload.sections) == 1:
            return self._frame_to_csv(payload.sections[0].dataframe)
        if not payload.sections:
            return self._frame_to_csv(self._summary_frame(payload))

        blocks = [f"# {self._SUMMARY_TITLE}", self._csv_text(self._summary_frame(payload))]
        for section in payload.sections:
            blocks.append(f"# {section.title}")
            blocks.append(self._csv_text(section.dataframe))
        return "\n".join(blocks).encode("utf-8")

    @staticmethod
    def _csv_text(df: pd.DataFrame) -> str:
        return df.to_csv(index=False, lineterminator="\n")

    def _frame_to_csv(self, df: pd.DataFrame) -> bytes:
        return self._csv_text(df).encode("utf-8")

    @staticmethod
    def _summary_frame(payload: ReportPayload) -> pd.DataFrame:
        return pd.DataFrame(
            {"metric": list(payload.summary.keys()), "value": list(payload.summary.values())}
        )

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
