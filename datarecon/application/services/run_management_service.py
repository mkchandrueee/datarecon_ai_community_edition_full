# datarecon/application/services/run_management_service.py
# Bulk operations over run history: extract many runs at once, archive them,
# or delete them permanently (ADR-0016).
#
# Run history accumulates faster than anything else in the tool — every
# scheduled tick adds rows. Acting on one run at a time is fine for inspecting
# a failure and useless for the two things people actually do with a backlog:
# hand a week of evidence to somebody, and clear out the noise.
from __future__ import annotations

import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO

import pandas as pd

from datarecon.application.services.reporting_service import (
    DEFAULT_BATCH_ROWS,
    ReportingService,
    sanitize_export_name,
)
from datarecon.application.services.test_suite_service import prefixed_name
from datarecon.domain.entities.validation_run import ValidationRun
from datarecon.domain.interfaces.validation_run_repository import IValidationRunRepository
from datarecon.infrastructure.persistence.run_detail_store import RunDetailStore

_MANIFEST_NAME = "manifest.csv"
_SUMMARY_NAME = "summary.csv"


@dataclass
class BulkRunResult:
    """What a bulk operation actually did, so the UI can report it honestly."""

    requested: int
    succeeded: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return self.requested - self.succeeded


class RunManagementService:
    def __init__(
        self,
        run_repository: IValidationRunRepository,
        detail_store: RunDetailStore,
        reporting_service: ReportingService,
    ):
        self._runs = run_repository
        self._details = detail_store
        self._reporting = reporting_service

    # ---------- retention ----------
    def archive_runs(self, run_ids: Sequence[str], archived: bool = True) -> BulkRunResult:
        """Hide (or restore) runs. Reversible, and the detail is untouched."""
        result = BulkRunResult(requested=len(run_ids))
        for run_id in run_ids:
            if self._runs.set_archived(run_id, archived):
                result.succeeded += 1
            else:
                result.missing.append(run_id)
        return result

    def delete_runs(self, run_ids: Sequence[str]) -> BulkRunResult:
        """Permanently remove runs and the row-level detail belonging to them.

        The detail goes first: if the metadata row were removed and then the
        Parquet delete failed, nothing would know the directory existed and it
        would sit on disk forever. Losing the detail while keeping the run is
        the recoverable direction of that race.
        """
        result = BulkRunResult(requested=len(run_ids))
        for run_id in run_ids:
            self._details.delete(run_id)
            if self._runs.delete(run_id):
                result.succeeded += 1
            else:
                result.missing.append(run_id)
        return result

    # ---------- extraction ----------
    def build_export(
        self, run_ids: Sequence[str], batch_rows: int = DEFAULT_BATCH_ROWS
    ) -> bytes:
        """A ZIP holding every selected run's summary and row-level detail.

        One folder per run, named after the run rather than its UUID, so the
        archive is readable by someone who was not the person who exported it.
        Oversized sections are split exactly as a single download would be
        (ADR-0013) — a 500,000-row CSV is no more openable for being zipped.
        """
        buffer = BytesIO()
        manifest_rows: list[dict[str, object]] = []

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            used_folders: set[str] = set()
            for run_id in run_ids:
                run = self._runs.get_by_id(run_id)
                if run is None:
                    continue
                folder = self._unique_folder(run, used_folders)
                manifest_rows.append(self._manifest_row(run, folder))

                archive.writestr(
                    f"{folder}/{_SUMMARY_NAME}", self._summary_csv(run)
                )
                for title, frame in self._details.load_all(run_id).items():
                    for batch in self._reporting.batch_frame(
                        sanitize_export_name(title), frame, batch_rows
                    ):
                        archive.writestr(
                            f"{folder}/{batch.name}.csv",
                            batch.dataframe.to_csv(index=False, lineterminator="\n"),
                        )

            # The manifest is what makes a folder of folders navigable: it says
            # what each one is without opening any of them.
            archive.writestr(
                _MANIFEST_NAME,
                pd.DataFrame(manifest_rows).to_csv(index=False, lineterminator="\n"),
            )
        return buffer.getvalue()

    @staticmethod
    def export_filename(run_count: int, when: datetime | None = None) -> str:
        stamp = (when or datetime.now(UTC)).strftime("%Y%m%d_%H%M")
        return f"DataRecon_Runs_{run_count}_{stamp}.zip"

    # ---------- helpers ----------
    def _summary_csv(self, run: ValidationRun) -> str:
        frame = pd.DataFrame(
            {"metric": list(run.summary.keys()), "value": list(run.summary.values())}
        )
        return frame.to_csv(index=False, lineterminator="\n")

    @staticmethod
    def _manifest_row(run: ValidationRun, folder: str) -> dict[str, object]:
        return {
            "folder": folder,
            "run_id": run.run_id,
            "module": run.module.value,
            "name": run.name,
            "status": run.status.value,
            "started_at": run.started_at.isoformat() if run.started_at else "",
            "runtime_seconds": run.runtime_seconds,
            "error_message": run.error_message or "",
        }

    @staticmethod
    def _unique_folder(run: ValidationRun, used: set[str]) -> str:
        """A readable folder name, disambiguated when two runs share one.

        The same suite re-run nightly produces the same label every time, so
        the run id is appended only when it is actually needed to tell two
        folders apart.
        """
        base = sanitize_export_name(prefixed_name(run.module, run.name))
        folder = base
        if folder in used:
            folder = f"{base}_{run.run_id[:8]}"
        used.add(folder)
        return folder
