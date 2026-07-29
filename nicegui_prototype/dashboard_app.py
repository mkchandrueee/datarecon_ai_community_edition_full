# nicegui_prototype/dashboard_app.py — NiceGUI Dashboard prototype (Module 19)
#
# Standalone prototype evaluating NiceGUI as a possible Streamlit
# replacement. Reuses the exact same composition-root services and SQLite
# repositories as app.py (Streamlit) — only the presentation layer
# differs here, which is the point: it proves the clean-architecture
# split (domain/application untouched) survives a UI framework swap.
#
# Not wired into app.py and not part of the routed application. Run it
# directly:
#   python nicegui_prototype/dashboard_app.py
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nicegui import ui

from config.settings import settings
from datarecon.application.services.dashboard_service import DashboardService
from datarecon.application.services.project_service import ProjectService
from datarecon.infrastructure.persistence.metadata_db import MetadataDatabase
from datarecon.infrastructure.persistence.sqlite_project_repository import (
    SQLiteProjectRepository,
)
from datarecon.infrastructure.persistence.sqlite_validation_run_repository import (
    SQLiteValidationRunRepository,
)

_metadata_db = MetadataDatabase(settings.metadata_db_path)
_project_service = ProjectService(SQLiteProjectRepository(_metadata_db))
_dashboard_service = DashboardService(SQLiteValidationRunRepository(_metadata_db))

_ALL_PROJECTS = "All Projects"


def _stat_card(label: str, value: str, color: str = "") -> None:
    with ui.card().classes("items-center px-6 py-4"):
        ui.label(value).classes(f"text-2xl font-bold {color}")
        ui.label(label).classes("text-sm text-gray-500")


@ui.page("/")
def dashboard_page() -> None:
    ui.label("Reconciliation Dashboard").classes("text-3xl font-bold")
    ui.label("NiceGUI prototype — Module 19").classes("text-sm text-gray-500 mb-2")

    projects = _project_service.list_projects()
    project_names = [_ALL_PROJECTS, *[p.name for p in projects]]
    project_id_by_name = {p.name: p.project_id for p in projects}
    state = {"project_id": None}

    @ui.refreshable
    def body() -> None:
        widgets = _dashboard_service.widgets(project_id=state["project_id"])
        if widgets.total_runs == 0:
            ui.label("No validation runs recorded for this selection yet.").classes(
                "text-gray-500 italic mt-4"
            )
            return

        with ui.row().classes("w-full gap-4"):
            _stat_card("Total Runs", f"{widgets.total_runs:,}")
            _stat_card("Passed", f"{widgets.passed:,}", color="text-green-600")
            _stat_card("Failed", f"{widgets.failed:,}", color="text-red-600")
            _stat_card("Errored", f"{widgets.errored:,}", color="text-orange-600")
            _stat_card("Pass Rate", f"{widgets.pass_rate_percent:.1f}%")

        trend = _dashboard_service.pass_rate_trend(project_id=state["project_id"])
        if not trend.empty:
            ui.label("Pass Rate Trend").classes("text-xl font-semibold mt-6")
            ui.echart(
                {
                    "xAxis": {"type": "category", "data": [str(d) for d in trend["date"]]},
                    "yAxis": {"type": "value", "max": 100},
                    "tooltip": {"trigger": "axis"},
                    "series": [
                        {
                            "type": "line",
                            "data": trend["pass_rate_percent"].tolist(),
                            "smooth": True,
                        }
                    ],
                }
            ).classes("w-full h-64")

        with ui.row().classes("w-full gap-4 items-start"):
            with ui.column().classes("flex-1"):
                ui.label("Runs by Module").classes("text-xl font-semibold mt-6")
                by_module = _dashboard_service.runs_by_module(project_id=state["project_id"])
                if not by_module.empty:
                    ui.table(
                        columns=[{"name": c, "label": c, "field": c} for c in by_module.columns],
                        rows=by_module.to_dict("records"),
                    ).classes("w-full")
                    ui.echart(
                        {
                            "xAxis": {"type": "category", "data": by_module["module"].tolist()},
                            "yAxis": {"type": "value"},
                            "tooltip": {"trigger": "axis"},
                            "legend": {},
                            "series": [
                                {"type": "bar", "name": s, "data": by_module[s].tolist()}
                                for s in ("passed", "failed", "errored")
                            ],
                        }
                    ).classes("w-full h-64")
            with ui.column().classes("flex-1"):
                ui.label("Runtime Trend").classes("text-xl font-semibold mt-6")
                runtime = _dashboard_service.runtime_trend(project_id=state["project_id"])
                if not runtime.empty:
                    ui.echart(
                        {
                            "xAxis": {
                                "type": "category",
                                "data": [str(t) for t in runtime["started_at"]],
                            },
                            "yAxis": {"type": "value"},
                            "tooltip": {"trigger": "axis"},
                            "series": [
                                {"type": "line", "data": runtime["runtime_seconds"].tolist()}
                            ],
                        }
                    ).classes("w-full h-64")

    def _on_project_change(value: str) -> None:
        state["project_id"] = project_id_by_name.get(value)
        body.refresh()

    ui.select(
        project_names, value=_ALL_PROJECTS, on_change=lambda e: _on_project_change(e.value)
    ).classes("w-64 mt-2").props("outlined dense")
    body()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="DataRecon AI — Dashboard (NiceGUI prototype)", port=8600, reload=False)
