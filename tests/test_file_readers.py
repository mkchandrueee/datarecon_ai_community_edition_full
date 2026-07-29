"""Unit tests — format-dispatched file readers (Module 1 File Sources / Module 13)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from datarecon.domain.enums import FileFormat
from datarecon.infrastructure.extraction.file_readers import read_file


def test_read_csv_from_path(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("id,name\n1,alice\n2,bob\n")
    df = read_file(str(path), FileFormat.CSV)
    assert list(df.columns) == ["id", "name"]
    assert len(df) == 2


def test_read_csv_from_buffer(tmp_path: Path) -> None:
    buf = BytesIO(b"id,name\n1,alice\n")
    df = read_file(buf, FileFormat.CSV)
    assert len(df) == 1


def test_read_csv_custom_delimiter(tmp_path: Path) -> None:
    path = tmp_path / "data.psv"
    path.write_text("id|name\n1|alice\n")
    df = read_file(str(path), FileFormat.CSV, {"delimiter": "|"})
    assert list(df.columns) == ["id", "name"]
    assert df.iloc[0]["name"] == "alice"


def test_read_excel(tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    pd.DataFrame({"id": [1, 2], "name": ["alice", "bob"]}).to_excel(path, index=False)
    df = read_file(str(path), FileFormat.EXCEL)
    assert len(df) == 2
    assert list(df.columns) == ["id", "name"]


def test_read_excel_named_sheet(tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="First", index=False)
        pd.DataFrame({"b": [2]}).to_excel(writer, sheet_name="Second", index=False)
    df = read_file(str(path), FileFormat.EXCEL, {"sheet_name": "Second"})
    assert list(df.columns) == ["b"]


def test_read_json_array(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text('[{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]')
    df = read_file(str(path), FileFormat.JSON)
    assert len(df) == 2
    assert set(df.columns) == {"id", "name"}


def test_read_json_ndjson_auto_detected(tmp_path: Path) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text('{"id": 1}\n{"id": 2}\n{"id": 3}\n')
    df = read_file(str(path), FileFormat.JSON)
    assert len(df) == 3


def test_read_xml(tmp_path: Path) -> None:
    path = tmp_path / "data.xml"
    path.write_text(
        "<root><row><id>1</id><name>alice</name></row><row><id>2</id><name>bob</name></row></root>"
    )
    df = read_file(str(path), FileFormat.XML)
    assert len(df) == 2
    assert set(df.columns) == {"id", "name"}


def test_read_parquet(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    pd.DataFrame({"id": [1, 2, 3]}).to_parquet(path, engine="pyarrow")
    df = read_file(str(path), FileFormat.PARQUET)
    assert len(df) == 3


def test_read_avro(tmp_path: Path) -> None:
    import fastavro

    path = tmp_path / "data.avro"
    schema = {
        "type": "record",
        "name": "Row",
        "fields": [{"name": "id", "type": "int"}, {"name": "name", "type": "string"}],
    }
    records = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    with open(path, "wb") as fh:
        fastavro.writer(fh, schema, records)

    df = read_file(str(path), FileFormat.AVRO)
    assert len(df) == 2
    assert list(df["name"]) == ["alice", "bob"]


def test_read_avro_from_buffer() -> None:
    import fastavro

    schema = {"type": "record", "name": "Row", "fields": [{"name": "id", "type": "int"}]}
    buf = BytesIO()
    fastavro.writer(buf, schema, [{"id": 1}, {"id": 2}])
    buf.seek(0)

    df = read_file(buf, FileFormat.AVRO)
    assert len(df) == 2


def test_unsupported_format_raises_key_error() -> None:
    with pytest.raises(KeyError):
        read_file("x", "not-a-real-format")  # type: ignore[arg-type]
