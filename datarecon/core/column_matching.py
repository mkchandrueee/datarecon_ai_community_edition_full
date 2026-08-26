# datarecon/core/column_matching.py
# Case-insensitive column-name resolution shared by every validation module.
#
# Databases disagree on identifier casing — Oracle folds to upper, Postgres to
# lower, others preserve what was quoted — so the same logical column shows up
# as CUSTOMER_ID on one side and customer_id on the other. Without this, Schema
# Validation reports one column as both MISSING_IN_TARGET and EXTRA_IN_TARGET,
# and the other modules reject a column the user can plainly see in the data.
#
# Column *names* are matched case-insensitively; column *values* are not
# affected (ComparisonConfig.ignore_case governs value comparison).
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def canonical_map(columns: Iterable[object]) -> dict[str, str]:
    """Map each column's case-folded name to its actual spelling.

    On a collision (a frame with both ID and id) the first spelling wins, so
    the mapping stays stable and callers keep the left-most column.
    """
    mapping: dict[str, str] = {}
    for column in columns:
        key = str(column).casefold()
        mapping.setdefault(key, str(column))
    return mapping


def resolve(name: str, columns: Iterable[object]) -> str | None:
    """Return the actual column matching `name` ignoring case, or None."""
    return canonical_map(columns).get(str(name).casefold())


def align_to_source(source: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Rename target columns that differ from source only by case.

    Modules that join or merge the two sides need one agreed spelling per
    column; source wins. Columns with no case-insensitive counterpart in
    source are left exactly as they are, so genuinely extra target columns
    still show up as extra.
    """
    canonical = canonical_map(source.columns)
    renames = {
        c: canonical[str(c).casefold()]
        for c in target.columns
        if str(c).casefold() in canonical and str(c) != canonical[str(c).casefold()]
    }
    return target.rename(columns=renames) if renames else target


def resolve_all(
    names: Sequence[str], columns: Iterable[object]
) -> tuple[list[str], list[str]]:
    """Resolve `names` against `columns` ignoring case.

    Returns (resolved, missing): `resolved` holds the actual spellings for the
    names that matched, `missing` the original names that did not — so error
    messages still quote what the user typed.
    """
    mapping = canonical_map(columns)
    resolved: list[str] = []
    missing: list[str] = []
    for name in names:
        actual = mapping.get(str(name).casefold())
        if actual is None:
            missing.append(name)
        else:
            resolved.append(actual)
    return resolved, missing
