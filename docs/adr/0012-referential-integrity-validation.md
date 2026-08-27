# ADR-0012: Referential Integrity is a first-class module, not a constraint check

## Status
Accepted

## Context
Reconciliation catches rows that differ between two copies of the same table,
but not rows that are internally inconsistent: an order pointing at a customer
that doesn't exist. That class of defect is common in exactly the situations
this tool exists for — data landed from files, replicated across databases, or
loaded into a warehouse where foreign keys were dropped for load performance.

Two questions had to be settled.

**Should the check be limited to declared foreign keys?** No. If the constraint
were enforced, the orphans could not exist. The cases worth finding are
precisely where the database is *not* enforcing the relationship, so the check
must work on any pair of columns the user names — including across two
different connections, where no constraint could span the gap.

**Are rows with a NULL foreign key orphans?** No. SQL's own referential rules
treat a NULL foreign key as "references nothing", not "references something
missing", and reporting them as orphans would drown the real defects in rows
that are working as designed. Whether that NULL is acceptable is a different
question, and Nullability Validation already answers it.

## Decision
- `ReferentialIntegrityService` checks that every child key value exists in the
  parent, over arbitrary column pairs on arbitrary connections. Composite keys
  pair positionally, matching how they work in SQL.
- NULL-keyed child rows are excluded from the check and reported separately as
  `null_key_rows`, so the exclusion is visible rather than silent. The orphan
  percentage is of **checked** rows, not all rows — a table that is 90% NULL
  keys should not look 90% healthy.
- Parent keys are de-duplicated before the join. Without that, a parent with
  repeated key values would fan the merge out and inflate the child row count,
  turning a clean result into a wrong one.
- A tolerance percentage is supported, because a known and accepted orphan rate
  (soft-deleted parents, for example) shouldn't fail every run.
- Full orphan **rows** are returned and persisted, not just the offending key
  values — the next question after "how many?" is always "which ones, and what
  else was on them?"
- The module reads declared foreign keys from the catalog (`ForeignKeyMetadata`
  via SQLAlchemy's Inspector) and offers them as one-click relationships. This
  is a convenience over the common case, not a constraint on what can be
  checked: the fields stay editable, and absence of a declared FK is not
  absence of a relationship.
- Column names resolve case-insensitively, consistent with ADR-0009, so a key
  spelled `CUSTOMER_ID` on one side and `customer_id` on the other still joins.

## Consequences
- Orphan detection works across databases and across file/table boundaries,
  which is where it is most needed and where the database itself cannot help.
- It runs in pandas on extracted frames, so it inherits the Community Edition
  row ceiling (ADR-0001). A pushdown `NOT EXISTS` against the source database
  would scale further and is the natural Enterprise extension.
- Because the check is not tied to declared constraints, a user can point it at
  a relationship that isn't real and get a meaningless answer. The detected-FK
  picker exists to make the correct setup the easy one.
