# ADR-0002: Community Edition module scope

## Status
Accepted

## Context
The Master PRD describes 37 modules spanning a full commercial-grade
platform (FastAPI/React Enterprise backend, multi-tenant SaaS, AI Copilot,
distributed agents, streaming validation, etc.). Section 2.1 explicitly
scopes the Community Edition down to a named subset. Building the full 37
modules in this codebase would contradict the PRD's own edition split and
is out of scope for a single-node Streamlit app with a SQLite metadata
store.

## Decision
This codebase implements exactly the Community Edition module list from
PRD 2.1, mapped to PRD module numbers:

| PRD Module | Status |
|---|---|
| 1 — Connection Management | Implemented (pre-existing, hardened) |
| 2 — Schema Validation | Implemented |
| 3 — Record Count Validation | Implemented |
| 4 — Duplicate Validation | Implemented |
| 5 — Nullability/Completeness Validation | Implemented |
| 6 — Full Data Validation | Implemented (pre-existing, reworked onto ADR-0001 backends) |
| 7 — Aggregation Validation | Implemented |
| 10 — Data Profiling | Implemented |
| 13 — File Comparison | Implemented |
| 18 — Reporting Engine | Implemented, Community scope only (Excel/CSV/PDF/JSON; no white-label branding, no scheduled distribution) |
| 19 — Reconciliation Dashboard | Implemented, Community scope only (single-node widgets/trend charts; no embeddable/shareable links, no role-scoped dashboards — Community has no multi-user RBAC) |

All other modules (8–9, 11–12, 14–17, 20–37) are Enterprise-only per PRD
2.2 (they require FastAPI/Celery/Postgres/Kubernetes, SSO/RBAC, or a React
frontend that Community Edition explicitly does not ship) and are **not**
implemented here. Where Community-scope reporting/dashboard functionality
overlaps with an Enterprise-only capability (e.g. white-label branded
reports, role-scoped dashboards), the Community version implements the
single-tenant/single-user subset only.

## Consequences
- No FastAPI/React/Kubernetes code is added to this repository; Community
  Edition remains Streamlit + SQLite + DuckDB/Polars, single node, per PRD
  2.1.
- Someone building the Enterprise Edition should treat this codebase's
  `datarecon.core` and `datarecon.domain` layers as reusable (they are
  framework-agnostic), but `datarecon.presentation` (Streamlit) and
  `datarecon.infrastructure.persistence` (SQLite) are Community-only and
  would be replaced, not extended, in Enterprise.
