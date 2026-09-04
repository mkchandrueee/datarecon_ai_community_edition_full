# datarecon/infrastructure/persistence/run_detail_store.py
# Parquet-backed, per-run row-level detail store (ADR-0008).
#
# ADR-0004 keeps the SQLite metadata store bounded to summary metrics only.
# This store is the separate, unbounded-growth-tolerant home for the actual
# result DataFrame(s) each module produces (mismatch rows, duplicate
# samples, null detail, profiling top-values, ...): one Parquet file per
# named "section" under data/run_details/<run_id>/, plus a small JSON
# manifest recording each section's display title (filenames are slugified
# and may collide/truncate, so the manifest is the source of truth for the
# original title).
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

_MANIFEST_NAME = "_manifest.json"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", title.strip()).strip("_")
    return slug or "section"


class RunDetailStore:
    """Persists and retrieves row-level result DataFrames for a validation run."""

    def __init__(self, base_dir: Path):
        self._base_dir = Path(base_dir)

    def save(self, run_id: str, details: Mapping[str, pd.DataFrame]) -> None:
        """Write each section's DataFrame to its own Parquet file. No-op if empty."""
        if not details:
            return
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        manifest: dict[str, str] = {}
        used_slugs: set[str] = set()
        for title, df in details.items():
            slug = self._unique_slug(title, used_slugs)
            df.to_parquet(run_dir / f"{slug}.parquet", index=False)
            manifest[slug] = title
        self._write_manifest(run_dir, manifest)

    def list_sections(self, run_id: str) -> list[str]:
        """Display titles of every section persisted for a run, in save order."""
        return list(self._read_manifest(run_id).values())

    def load(self, run_id: str, section: str) -> pd.DataFrame | None:
        """Load one section's DataFrame by its display title, or None if absent."""
        manifest = self._read_manifest(run_id)
        slug = next((s for s, title in manifest.items() if title == section), None)
        if slug is None:
            return None
        path = self._run_dir(run_id) / f"{slug}.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def load_all(self, run_id: str) -> dict[str, pd.DataFrame]:
        """Load every persisted section for a run, keyed by display title."""
        manifest = self._read_manifest(run_id)
        run_dir = self._run_dir(run_id)
        sections = {}
        for slug, title in manifest.items():
            path = run_dir / f"{slug}.parquet"
            if path.exists():
                sections[title] = pd.read_parquet(path)
        return sections

    def has_detail(self, run_id: str) -> bool:
        return self._manifest_path(run_id).is_file()

    def delete(self, run_id: str) -> bool:
        """Remove every stored section for a run. False if there was nothing.

        Deleting a run has to take its detail with it: the metadata row is the
        only thing that knows this directory exists, so leaving the Parquet
        behind would strand it on disk for good.
        """
        run_dir = self._run_dir(run_id)
        if not run_dir.is_dir():
            return False
        for path in sorted(run_dir.iterdir()):
            if path.is_file():
                path.unlink()
        run_dir.rmdir()
        return True

    # ------------------------------------------------------------------ #
    def _run_dir(self, run_id: str) -> Path:
        return self._base_dir / run_id

    def _manifest_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / _MANIFEST_NAME

    def _read_manifest(self, run_id: str) -> dict[str, str]:
        path = self._manifest_path(run_id)
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_manifest(run_dir: Path, manifest: dict[str, str]) -> None:
        (run_dir / _MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    @staticmethod
    def _unique_slug(title: str, used: set[str]) -> str:
        base = _slugify(title)
        slug, i = base, 1
        while slug in used:
            slug = f"{base}_{i}"
            i += 1
        used.add(slug)
        return slug
