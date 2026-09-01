# ADR-0015: Explain differences by detecting them, not by describing them to a model

## Status
Accepted

## Context
A Full Data Validation over a large table can report a hundred thousand
mismatched rows. That answers "how many" and leaves the expensive question —
*what actually happened?* — to a person scrolling a grid.

In practice the answer is almost always one mechanical cause repeated across
every row: a units change, a column that arrived NULL, a timezone offset, a
truncated load, a target column narrower than the source. These causes are
uniform by construction, which makes them exactly the shapes a computer can
find and exactly the shapes a reader would have to scroll thousands of rows to
notice.

The obvious implementation was to send a sample of mismatched rows to an LLM
and ask what it saw. That was rejected, for reasons specific to this problem
rather than a general position on models:

- **A wrong explanation is worse than none.** It sends someone to fix the wrong
  system, and it is delivered in the same confident register as a right one.
  "All off by exactly 100×" is a claim about *every* row — a sample cannot
  support it, and arithmetic can.
- **The findings must be reproducible.** A reconciliation report is evidence in
  an argument between two teams. An explanation that varies between runs of the
  same data is not usable in that argument.
- **The data must not leave the box.** The rows being explained are the
  customer records that failed to reconcile. Community Edition is a single-node
  on-prem tool with no API key and no egress; that is a feature of the
  deployment, not an oversight.
- **The patterns are cheap to compute exactly.** Constant ratio, constant
  offset, constant timedelta, prefix truncation, case- and whitespace-only
  differences, all-NULL columns, contiguous key blocks — each is a few
  vectorised operations over a column that is already in memory.

## Decision
- `datarecon/core/mismatch_patterns.py` analyses the engine's diff frame and
  returns ranked `Pattern` objects, each with a headline, supporting detail,
  the column, and the number of rows it accounts for. The UI leads with the
  best one, above the grid.
- **Every claim is checked against every row it covers.** A detector fires only
  when the property holds for the whole set — the word "exactly" in a headline
  is literal, up to floating-point noise (`rtol=1e-9`, since float arithmetic
  never reproduces a ratio bit-for-bit).
- **Silence beats a guess.** Fewer than three rows produces no claim at all —
  two rows agreeing on a ratio is a coincidence. Data with no uniform structure
  yields the column concentration and nothing more.
- Detectors run in a fixed order per column and the first match wins, so a
  cause is reported once in its most specific form: a sign flip is named a sign
  flip rather than a −1 ratio; a difference too small to matter is named
  rounding rather than an offset.
- Where a finding maps to an existing comparison option, it says so — case- and
  whitespace-only differences point at "Ignore case" and "Trim strings", tiny
  numeric differences at the float tolerance. The most useful explanation of a
  failure is often that the comparison was configured too strictly.
- Row *sets* get their own analysis: missing or extra rows whose keys form an
  unbroken block are reported as a partial load, which is a different defect
  from rows failing individually and the one a row list hides best.
- Reports run the same analysis on stored detail. Business keys are recovered
  from the diff frame's own shape (the columns with no `_source`/`_target`
  twin), so a run from last night is explained like one just executed.

## Consequences
- The common causes are named in one sentence instead of found by scrolling,
  and the sentence is defensible: it is arithmetic over the full result.
- The detector set is finite. A cause nobody wrote a detector for is not
  reported — the tool goes quiet rather than speculating, and adding a
  detector is a small, testable change.
- This is deterministic analysis with templated phrasing, not a language model,
  and should not be described as one. The place a model would genuinely add
  something is the residue: explaining a pattern no detector covers, or
  relating a finding to a schema or pipeline it cannot see from the data. That
  needs an egress and privacy story this edition does not have, and it belongs
  behind the same port shape when it does.
