# datarecon/infrastructure/extraction/file_readers.py  (NEW)
# Format-dispatched readers (PRD Module 1 File Sources / Module 13 inputs).
# Every reader accepts a local path or an in-memory buffer, so the same code
# path serves local files AND cloud-storage objects.
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

from datarecon.domain.enums import FileFormat

Source = str | BytesIO


def read_file(
    source: Source,
    file_format: FileFormat,
    options: dict[str, Any] | None = None,
) -> pd.DataFrame:
    opts = dict(options or {})
    reader = _READERS[file_format]
    return reader(source, opts)


def _read_csv(source: Source, opts: dict[str, Any]) -> pd.DataFrame:
    return pd.read_csv(
        source,
        sep=opts.pop("delimiter", ","),
        encoding=opts.pop("encoding", "utf-8"),
        **opts,
    )


def _read_excel(source: Source, opts: dict[str, Any]) -> pd.DataFrame:
    return pd.read_excel(source, sheet_name=opts.pop("sheet_name", 0), **opts)


def _read_json(source: Source, opts: dict[str, Any]) -> pd.DataFrame:
    lines = opts.pop("lines", None)
    if lines is None:  # auto-detect NDJSON
        head = _peek(source, 2048).lstrip()
        lines = not head.startswith(("[", "{")) or (head.startswith("{") and "\n{" in head)
    df = pd.read_json(source, lines=bool(lines), **opts)
    # Flatten one level of nesting for record-style payloads.
    if any(isinstance(v, dict) for v in df.iloc[0].values) if len(df) else False:
        df = pd.json_normalize(df.to_dict(orient="records"))
    return df


def _read_xml(source: Source, opts: dict[str, Any]) -> pd.DataFrame:
    return (
        pd.read_xml(
            source, xpath=opts.pop("xpath", ".//*[local-name()='row'] | ./*"), parser="lxml", **opts
        )
        if opts.get("xpath")
        else pd.read_xml(source, parser="lxml", **opts)
    )


def _read_parquet(source: Source, opts: dict[str, Any]) -> pd.DataFrame:
    return pd.read_parquet(source, engine="pyarrow", **opts)


def _read_avro(source: Source, opts: dict[str, Any]) -> pd.DataFrame:
    import contextlib

    import fastavro

    with contextlib.ExitStack() as stack:
        fh = stack.enter_context(open(source, "rb")) if isinstance(source, str) else source
        records = list(fastavro.reader(fh))
    return pd.DataFrame.from_records(records, **opts)


def _peek(source: Source, n: int) -> str:
    if isinstance(source, str):
        with open(source, encoding="utf-8", errors="ignore") as fh:
            return fh.read(n)
    pos = source.tell()
    data = source.read(n)
    source.seek(pos)
    return data.decode("utf-8", errors="ignore")


_READERS = {
    FileFormat.CSV: _read_csv,
    FileFormat.EXCEL: _read_excel,
    FileFormat.JSON: _read_json,
    FileFormat.XML: _read_xml,
    FileFormat.PARQUET: _read_parquet,
    FileFormat.AVRO: _read_avro,
}
