# ADR-0011: Validation SQL is generated from catalog metadata, not a language model

## Status
Accepted

## Context
Setting up validations means writing the same `SELECT` by hand for both sides
of four modules, for every table. It is the most repetitive part of onboarding
a reconciliation, and a mistyped column name only surfaces when the run fails.
The request was to add an "AI button" that writes this SQL from a table name.

Two implementations were possible:

1. **Call a language model.** Flexible, and the obvious reading of "AI". But
   it needs an API key per user, network access from what is otherwise an
   offline single-node tool, costs money per click, and — decisively — can
   hallucinate a column that does not exist. The user cannot tell a wrong
   column from a right one until the validation errors out.
2. **Read the database's own catalog.** SQLAlchemy's Inspector already backs
   Schema Validation's length/key/default comparison (ADR-0007), so the exact
   column list, primary key and nullability are already available.

The second is not a lesser version of the first here. The task is fully
determined by metadata the database can state authoritatively, so a model
would be guessing at something we can simply look up.

There is also a correctness trap a model would plausibly fall into. Record
Count counts the **rows of the extracted frame**, not a scalar the query
returns — so the natural-looking `SELECT COUNT(*) FROM t` yields a single row
and reports a count of **1**. Every generated query must be row-returning.

## Decision
- `SqlGenerationService` generates SQL from `ColumnCatalogMetadata`. It can
  only ever reference columns the catalog reports, so the output is correct by
  construction rather than by review.
- Every generated statement is row-returning. The Record Count statement
  carries a note explaining why it is not `COUNT(*)`, so the next person to
  read it does not "fix" it.
- The generator returns what it inferred alongside the SQL:
  - **Duplicate** — the primary key, pre-filled as the duplicate key.
  - **Nullability** — the NOT NULL columns, since a null there is a genuine
    defect rather than a permitted absence.
- Identifiers are quoted **only when they need it**, using the dialect's quote
  characters (backticks for MySQL/Hive/Spark/Databricks, brackets for SQL
  Server/Azure SQL/Synapse, double quotes elsewhere). A plain name left
  unquoted lets the database apply its own case folding — the same thing an
  unquoted name in the user's DDL would have done.
- Bulk generation takes a list of tables and returns a per-table result. A
  table that cannot be introspected reports its reason on its own result
  instead of aborting the batch, and the Bulk Setup page names the failures.
- Generated SQL is staged in session state under a `_query_pending` key and
  moved into the Custom SQL box by `extraction_inputs()` *before* that widget
  is created. Streamlit rejects writes to a live widget's own state key, so
  writing it directly raises `StreamlitAPIException`.

## Consequences
- The feature works offline, costs nothing per use, returns instantly, and
  cannot invent a column.
- It is bounded to what the catalog knows: it cannot write a join, a filter or
  a business rule. Those stay hand-written, which is the honest division —
  they depend on intent the database cannot supply.
- Connections without introspection (files, and NoSQL sources) get a clear
  "no catalog metadata" message rather than a wrong guess.
- An LLM path can be layered on later for the genuinely open-ended cases
  (natural-language rules, mismatch explanation) without disturbing this one,
  since the deterministic generator remains the default and needs no key.
