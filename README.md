# DataRecon AI — Community Edition

Single-node data validation and reconciliation: compare schemas, counts,
duplicates, nullability, aggregates, and full row-level data between any
two connections (databases, cloud storage, or local files), profile a
dataset, and track pass/fail history on a dashboard.

This is the **Community Edition** described in section 2.1 of the
[Master PRD](docs/adr) — free, single-node, Streamlit UI, SQLite metadata
store, DuckDB/Polars-backed compare engine. The full enterprise platform
(FastAPI/React, multi-tenant SaaS, AI Copilot, distributed agents, etc.)
is out of scope for this codebase; see [ADR-0002](docs/adr/0002-community-edition-module-scope.md)
for the exact module boundary and rationale.

## Modules

| # | Module | What it does |
|---|--------|---------------|
| 1 | Connections | Create/test/clone connections across 30+ database, storage, and file source types |
| 2 | Schema Validation | Compare column name/position/type between source and target |
| 3 | Record Count Validation | Row counts with absolute/percent tolerance, optional group-by breakdown |
| 4 | Duplicate Validation | Detect duplicate rows by key column(s) |
| 5 | Nullability Validation | Null/blank/sentinel-value detection with a completeness score |
| 6 | Full Data Validation | Key-based row-level diff: matched / mismatched / missing / extra |
| 7 | Aggregation Validation | COUNT/SUM/AVG/MIN/MAX/COUNT(DISTINCT) comparison |
| 10 | Data Profiling | Per-column statistics, top-N values, semantic type inference |
| 13 | File Comparison | Structure/count/full-data/checksum comparison between two files |
| 18 | Reporting | Export any result to Excel, CSV, PDF, or JSON |
| 19 | Dashboard | Pass/fail widgets and trend charts over run history |

## Quickstart

```bash
# Core install (Postgres, MySQL, SQL Server, Oracle, MongoDB, local files)
pip install -e .

# + one or more optional connector groups
pip install -e ".[warehouse]"   # Snowflake, DB2, Teradata, Redshift, Databricks, SAP HANA
pip install -e ".[bigdata]"     # Hive / Spark Thrift
pip install -e ".[jdbc]"        # Generic JDBC (requires a JVM)
pip install -e ".[cloud]"       # AWS S3, Azure Blob/ADLS, Google Cloud Storage
pip install -e ".[all]"         # everything above

streamlit run app.py
```

The app opens at `http://localhost:8501`. Metadata (connections and run
history) is stored in a local SQLite file at `data/datarecon_meta.db`,
and connection credentials are encrypted at rest with a key generated on
first run at `data/.datarecon.key` (owner-only file permissions).

### Configuration

Environment variables (or a `.env` file — see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `DATARECON_KEY_PATH` | `data/.datarecon.key` | Path to the Fernet encryption key for stored credentials |
| `DATARECON_CONNECT_TIMEOUT` | `10` | Connection test timeout, in seconds |
| `DATARECON_SCHEDULE_TZ` | `UTC` | Timezone cron schedules are read in |
| `DATARECON_SCHEDULER_INTERVAL` | `60` | Seconds between scheduler ticks |
| `DATARECON_NOTIFY_ON` | `failure` | `failure`, `always`, or `never` |
| `DATARECON_SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_TLS` | — | SMTP server for email notifications |
| `DATARECON_NOTIFY_FROM` / `DATARECON_NOTIFY_TO` | — | Sender, and comma-separated recipients |
| `DATARECON_NOTIFY_WEBHOOK` | — | Slack/Teams incoming-webhook URL |

## Scheduling

Give a Test Suite a cron schedule on the **Test Suites** page, then run the
scheduler — it is a separate process, because a Streamlit server only executes
code while a browser session is driving it.

```bash
python -m datarecon.scheduler            # tick every minute until stopped
python -m datarecon.scheduler --once     # one tick, for OS cron / Task Scheduler
python -m datarecon.scheduler --list     # what is scheduled, and when it next fires
```

Notifications go out when a scheduled run fails, over email and/or an incoming
webhook — whichever the environment above configures. No channel configured is
a valid setup: schedules still run and results are still recorded. Missed
minutes are not caught up, so a scheduler that was down does not fire a backlog
when it returns. See ADR-0014 for the reasoning.

## Development

```bash
pip install -e ".[dev]"
pre-commit install        # optional but recommended: ruff + mypy on every commit

pytest                    # runs the full suite with coverage (pyproject.toml config)
ruff check . --fix        # lint
ruff format .             # format
mypy                      # type-check
```

The test suite (200+ tests) runs against real SQLite databases and local
files wherever practical, and against injected fakes for connectors that
need a live external service (ODBC, MongoDB, cloud storage). Tests for
optional-extra database dialects skip cleanly on a core-only install and
run for real once the relevant extra is installed — see
[ADR-0003](docs/adr/0003-optional-connector-extras.md).

## Architecture

Clean/Hexagonal layering, consistent across every module:

```
datarecon/
├── domain/            # entities, enums, repository interfaces — no framework deps
├── application/        # services: one per module, orchestrate domain + infrastructure
├── infrastructure/     # SQLite persistence, DB/storage connectors, extraction, crypto
├── core/engine/         # framework-agnostic comparison + DuckDB query engine
└── presentation/        # Streamlit views, one per module, thin over the services
```

Every validation module follows the same shape: a `*Request` dataclass in,
extraction via `DataExtractionService`, computation via DuckDB SQL (or the
dedicated Pandas engine for Module 6 — see [ADR-0001](docs/adr/0001-compare-engine-duckdb-polars-pandas.md)),
a `*Result` dataclass out, and a `ValidationRun` summary persisted for the
dashboard (see [ADR-0004](docs/adr/0004-run-history-summary-only-persistence.md)).

See [`docs/adr/`](docs/adr/) for the recorded architecture decisions,
including scope cuts and their rationale.

## License

Apache-2.0 — see [LICENSE](LICENSE).
