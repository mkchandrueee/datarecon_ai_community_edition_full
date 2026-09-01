"""Unit tests — the five-field cron parser (ADR-0014)."""

from __future__ import annotations

from datetime import datetime

import pytest

from datarecon.core.cron import CronError, CronSchedule


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


# ---------- parsing ----------


def test_wildcard_fires_every_minute() -> None:
    schedule = CronSchedule.parse("* * * * *")
    assert schedule.matches(at("2026-03-05T13:47"))


def test_fixed_minute_and_hour() -> None:
    schedule = CronSchedule.parse("30 6 * * *")
    assert schedule.matches(at("2026-03-05T06:30"))
    assert not schedule.matches(at("2026-03-05T06:31"))
    assert not schedule.matches(at("2026-03-05T07:30"))


def test_list_of_values() -> None:
    schedule = CronSchedule.parse("0 6,12,18 * * *")
    assert [schedule.matches(at(f"2026-03-05T{h:02}:00")) for h in (6, 12, 18)] == [True] * 3
    assert not schedule.matches(at("2026-03-05T09:00"))


def test_range_of_values() -> None:
    schedule = CronSchedule.parse("0 9-17 * * *")
    assert schedule.matches(at("2026-03-05T09:00"))
    assert schedule.matches(at("2026-03-05T17:00"))
    assert not schedule.matches(at("2026-03-05T18:00"))


def test_step_over_wildcard() -> None:
    schedule = CronSchedule.parse("*/15 * * * *")
    assert sorted(schedule.minutes) == [0, 15, 30, 45]


def test_step_over_range() -> None:
    schedule = CronSchedule.parse("0 8-16/4 * * *")
    assert sorted(schedule.hours) == [8, 12, 16]


def test_weekday_names_are_accepted() -> None:
    schedule = CronSchedule.parse("0 6 * * mon-fri")
    assert schedule.matches(at("2026-03-05T06:00"))  # a Thursday
    assert not schedule.matches(at("2026-03-07T06:00"))  # Saturday


def test_month_names_are_accepted() -> None:
    schedule = CronSchedule.parse("0 0 1 jan *")
    assert schedule.matches(at("2026-01-01T00:00"))
    assert not schedule.matches(at("2026-02-01T00:00"))


def test_seven_means_sunday() -> None:
    """Vixie cron accepts both 0 and 7 for Sunday."""
    assert CronSchedule.parse("0 0 * * 7").matches(at("2026-03-08T00:00"))
    assert CronSchedule.parse("0 0 * * 0").matches(at("2026-03-08T00:00"))


def test_presets_expand() -> None:
    assert CronSchedule.parse("@daily").expression == "0 0 * * *"
    assert CronSchedule.parse("@HOURLY").minutes == frozenset({0})


# ---------- the day-field OR rule ----------


def test_both_day_fields_restricted_means_or_not_and() -> None:
    """Cron fires on the day-of-month OR the day-of-week when both are set."""
    schedule = CronSchedule.parse("0 0 1 * 1")  # 1st of the month, and Mondays
    assert schedule.matches(at("2026-03-01T00:00"))  # a Sunday, but the 1st
    assert schedule.matches(at("2026-03-02T00:00"))  # a Monday, not the 1st
    assert not schedule.matches(at("2026-03-03T00:00"))  # neither


def test_one_day_field_restricted_still_means_and() -> None:
    schedule = CronSchedule.parse("0 0 15 * *")
    assert schedule.matches(at("2026-03-15T00:00"))
    assert not schedule.matches(at("2026-03-16T00:00"))


# ---------- next_runs ----------


def test_next_runs_are_strictly_after_the_given_moment() -> None:
    schedule = CronSchedule.parse("0 6 * * *")
    runs = schedule.next_runs(at("2026-03-05T06:00"), 2)
    assert runs == [at("2026-03-06T06:00"), at("2026-03-07T06:00")]


def test_next_runs_returns_the_requested_count() -> None:
    runs = CronSchedule.parse("*/10 * * * *").next_runs(at("2026-03-05T13:03"), 3)
    assert runs == [at("2026-03-05T13:10"), at("2026-03-05T13:20"), at("2026-03-05T13:30")]


def test_next_runs_ignores_seconds_on_the_starting_moment() -> None:
    runs = CronSchedule.parse("* * * * *").next_runs(at("2026-03-05T13:03:45"), 1)
    assert runs == [at("2026-03-05T13:04")]


def test_next_runs_of_zero_is_empty() -> None:
    assert CronSchedule.parse("* * * * *").next_runs(at("2026-03-05T13:00"), 0) == []


# ---------- rejection ----------


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "* * * *",  # four fields
        "* * * * * *",  # six fields
        "60 * * * *",  # minute out of range
        "* 24 * * *",  # hour out of range
        "* * 0 * *",  # day-of-month is 1-based
        "* * * 13 *",  # month out of range
        "* * * * 8",  # day-of-week out of range
        "5-1 * * * *",  # backwards range
        "*/0 * * * *",  # zero step
        "abc * * * *",  # not a number
    ],
)
def test_invalid_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(CronError):
        CronSchedule.parse(expression)


def test_the_error_names_the_field_that_is_wrong() -> None:
    with pytest.raises(CronError, match="hour"):
        CronSchedule.parse("0 99 * * *")
