# datarecon/core/cron.py
# A five-field cron expression, parsed and matched without a third-party
# scheduler library (ADR-0014). Community Edition deliberately carries no
# scheduler infrastructure, and the useful subset of cron — wildcards, lists,
# ranges and steps — is small enough to own outright and test exactly.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

#: (name, low, high) per cron position. Day-of-week is 0-6 with Sunday as 0;
#: 7 is also accepted as Sunday, as in Vixie cron.
_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 6),
)

_MONTH_NAMES = {
    name: i
    for i, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
_DAY_NAMES = {
    name: i for i, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))
}

#: How far ahead `next_runs` will look before giving up. A schedule that never
#: fires within four years (29 February on a non-leap cycle, say) has no next
#: run worth waiting for, and an unbounded search would simply hang.
_MAX_LOOKAHEAD_MINUTES = 4 * 366 * 24 * 60

_PRESETS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


class CronError(ValueError):
    """Raised for a cron expression that cannot be parsed."""


@dataclass(frozen=True)
class CronSchedule:
    """A parsed cron expression, matched minute by minute."""

    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    #: True when both day fields are restricted. Cron treats that as OR, not
    #: AND — `0 0 1 * 1` fires on the 1st *and* on every Monday.
    day_fields_are_or: bool

    @classmethod
    def parse(cls, expression: str) -> CronSchedule:
        raw = (expression or "").strip()
        if not raw:
            raise CronError("A cron expression is required.")
        raw = _PRESETS.get(raw.casefold(), raw)

        parts = raw.split()
        if len(parts) != 5:
            raise CronError(
                f"A cron expression needs 5 fields "
                f"(minute hour day-of-month month day-of-week), got {len(parts)}."
            )

        values = [
            _parse_field(part, name, low, high)
            for part, (name, low, high) in zip(parts, _FIELDS, strict=True)
        ]
        return cls(
            expression=raw,
            minutes=values[0],
            hours=values[1],
            days_of_month=values[2],
            months=values[3],
            days_of_week=values[4],
            day_fields_are_or=parts[2] != "*" and parts[4] != "*",
        )

    def matches(self, when: datetime) -> bool:
        """True when `when`'s minute is one this schedule fires on."""
        if when.minute not in self.minutes or when.hour not in self.hours:
            return False
        if when.month not in self.months:
            return False
        # Python's weekday() is Monday=0; cron's is Sunday=0.
        day_of_week = (when.weekday() + 1) % 7
        dom_ok = when.day in self.days_of_month
        dow_ok = day_of_week in self.days_of_week
        return (dom_ok or dow_ok) if self.day_fields_are_or else (dom_ok and dow_ok)

    def next_runs(self, after: datetime, count: int = 3) -> list[datetime]:
        """The next `count` firing times strictly after `after`.

        Used to show a person what their expression actually means before they
        save it — a cron field is easy to write and hard to read back.
        """
        if count < 1:
            return []
        cursor = after.replace(second=0, microsecond=0)
        found: list[datetime] = []
        for _ in range(_MAX_LOOKAHEAD_MINUTES):
            cursor += timedelta(minutes=1)
            if self.matches(cursor):
                found.append(cursor)
                if len(found) == count:
                    break
        return found


def _parse_field(part: str, name: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for piece in part.split(","):
        values |= _parse_piece(piece, name, low, high)
    if not values:
        raise CronError(f"The {name} field '{part}' matches nothing.")
    return frozenset(values)


def _parse_piece(piece: str, name: str, low: int, high: int) -> set[int]:
    piece = piece.strip()
    if not piece:
        raise CronError(f"The {name} field has an empty entry.")

    step = 1
    if "/" in piece:
        piece, _, step_text = piece.partition("/")
        step = _to_int(step_text, name)
        if step < 1:
            raise CronError(f"The {name} step must be 1 or more, got '{step_text}'.")

    if piece in ("*", ""):
        start, end = low, high
    elif "-" in piece.lstrip("-"):
        start_text, _, end_text = piece.partition("-")
        start = _to_value(start_text, name, low, high)
        end = _to_value(end_text, name, low, high)
        if start > end:
            raise CronError(f"The {name} range '{piece}' runs backwards.")
    else:
        start = end = _to_value(piece, name, low, high)

    return set(range(start, end + 1, step))


def _to_value(text: str, name: str, low: int, high: int) -> int:
    key = text.strip().casefold()
    if name == "month" and key in _MONTH_NAMES:
        return _MONTH_NAMES[key]
    if name == "day of week" and key in _DAY_NAMES:
        return _DAY_NAMES[key]

    value = _to_int(text, name)
    # Vixie cron accepts 7 for Sunday alongside 0; normalise rather than reject.
    if name == "day of week" and value == 7:
        return 0
    if not low <= value <= high:
        raise CronError(f"The {name} value {value} is outside {low}-{high}.")
    return value


def _to_int(text: str, name: str) -> int:
    try:
        return int(text.strip())
    except ValueError:
        raise CronError(f"The {name} field has a non-numeric value '{text.strip()}'.") from None
