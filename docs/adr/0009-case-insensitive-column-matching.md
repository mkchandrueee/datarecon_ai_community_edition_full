# ADR-0009: Column names are matched case-insensitively

## Status
Accepted

## Context
Databases disagree on how they fold unquoted identifiers: Oracle and DB2
upper-case them, PostgreSQL lower-cases them, SQL Server and MySQL depend
on collation, and files carry whatever header the producer wrote. A
source-to-target reconciliation almost always crosses that boundary, so
the same logical column arrives as `CUSTOMER_ID` on one side and
`customer_id` on the other.

Treating those as different columns produced results that were not just
unhelpful but actively wrong:

- Full Data Validation refused to run at all —
  `Business key(s) ['CUSTOMER_ID'] not found in target columns` — even
  though the column was plainly there.
- Schema Validation reported a single matching column as **both**
  `MISSING_IN_TARGET` and `EXTRA_IN_TARGET`, inflating the mismatch count
  and failing a run that should have passed.
- Duplicate, Nullability, Aggregation and Profiling rejected a column
  name the user could see in their own data.

Requiring users to hand-match casing per module is not a fix: they often
cannot change either schema, and the casing is an artifact of the engine,
not a meaningful difference in the data.

## Decision
- Column **names** are matched case-insensitively everywhere. Column
  **values** are unaffected — `ComparisonConfig.ignore_case` continues to
  govern value comparison, and the two are deliberately separate settings.
- `datarecon/core/column_matching.py` holds the shared primitives:
  `canonical_map()`, `resolve()`, `resolve_all()` and `align_to_source()`.
  One implementation, so the modules cannot drift apart on this.
- **Source spelling is canonical.** Where two sides are compared, target
  columns that differ only by case are renamed to the source's spelling,
  so outputs, exports and mismatch reports use one consistent name.
- User-supplied names (business keys, group-by columns, compare columns,
  profiled columns) resolve against the actual data case-insensitively.
  Error messages still quote the name **as the user typed it**, since
  that is what they need to correct.
- `ComparisonEngine` gained `ComparisonConfig.case_insensitive_columns`
  (default `True`) so the strict behaviour remains available for a
  caller that genuinely wants case-sensitive identity.
- On a frame that contains both `ID` and `id`, the first spelling wins.
  This is rare, ambiguous by nature, and a stable rule beats a crash.

## Consequences
- Cross-database reconciliation works without the user renaming columns
  or rewriting queries to force a casing.
- Schema Validation's mismatch counts are now correct across engines
  that fold identifiers differently; a run that previously failed with
  two phantom mismatches per column now passes.
- A team that deliberately keeps `ID` and `id` as distinct columns in one
  table gets the first one. No real schema in the PRD's target
  environments does this, and `case_insensitive_columns=False` is the
  escape hatch for a comparison that must be strict.
- Matching is `str.casefold()`, not `str.lower()`, so non-ASCII
  identifiers fold correctly too.
