# ADR-0003: Optional connector extras instead of one monolithic dependency set

## Status
Accepted

## Context
The original `requirements.txt` pinned ~30 packages unconditionally,
including heavyweight/niche enterprise drivers (Snowflake, Databricks,
DB2, Teradata, Redshift, SAP HANA, Hive/Spark via PyHive+thrift,
generic JDBC via JPype). Two of those pins were mutually unresolvable
(`pyarrow==17.0.0` vs. `databricks-sqlalchemy`'s `pyarrow<17` constraint;
`sqlalchemy-redshift==0.8.14` vs. the rest of the stack's SQLAlchemy 2.x
requirement) — the file had never been installed end-to-end as committed.
Separately, `EngineFactory`/`DBAPIConnectorFactory` already lazy-import
each driver only when a connection of that specific type is created, so
the Python-level coupling to any one driver is already optional; the
dependency manifest didn't reflect that.

## Decision
Split `pyproject.toml` into:
- **Core** (always installed): Streamlit, Pandas/NumPy, DuckDB, Polars,
  PyArrow, SQLAlchemy, cryptography, and the drivers common enough for a
  solo engineer's Community Edition install — PostgreSQL, MySQL, SQL
  Server (pyodbc), Oracle, MongoDB — plus file/report libraries
  (openpyxl, lxml, fastavro, xlsxwriter, reportlab).
- **`warehouse` extra**: Snowflake, DB2, Teradata, Redshift, Databricks,
  SAP HANA.
- **`bigdata` extra**: PyHive (Hive/Spark Thrift).
- **`jdbc` extra**: JayDeBeApi/JPype1 (requires a JVM).
- **`cloud` extra**: boto3, Azure Storage/Identity, Google Cloud Storage.
- **`all`**: union of the above, for full-matrix CI or a "kitchen sink"
  install.

Also fixed three unresolvable/broken pins:
- `pyarrow` relaxed to `>=14.0.1,<17.0.0` (was `==17.0.0`, conflicting
  with `databricks-sqlalchemy`'s `pyarrow<17`).
- `sqlalchemy-redshift` bumped to `1.0.0` (was `0.8.14`, which requires
  `SQLAlchemy<2.0.0` — incompatible with the rest of the stack).
- `SQLAlchemy` bumped to `==2.0.43` (was `2.0.32`): `sqlalchemy-redshift`
  1.0.0 imports `DBAPIModule` from `sqlalchemy.engine.interfaces`, which
  doesn't exist before SQLAlchemy ~2.0.43 — installing the `warehouse`
  extra against the original pin raised `ImportError` on the Redshift
  dialect. Found by actually installing the `warehouse` extra and running
  `tests/test_engine_factory.py` against it rather than trusting a clean
  `pip install -e .` (core-only) run.

## Consequences
- `pip install -e .` (core) is fast and has no native-build surprises;
  `pip install -e ".[all]"` pulls the full PRD Module 1 connector matrix
  for environments that need it.
- Tests exercising an optional-extra driver use
  `pytest.importorskip(..., exc_type=ImportError)` so the suite is green
  on a core-only install and still exercises the real driver when the
  extra is present (see `tests/test_engine_factory.py`).
- New drivers added later should default into an extra unless they are as
  common as Postgres/MySQL/SQL Server/Oracle/Mongo.
