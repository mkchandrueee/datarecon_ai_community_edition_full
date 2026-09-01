"""Unit tests — SchedulerService (unattended execution + notifications, ADR-0014)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from datarecon.application.services.aggregation_validation_service import (
    AggregationValidationService,
)
from datarecon.application.services.duplicate_validation_service import (
    DuplicateValidationService,
)
from datarecon.application.services.full_data_validation_service import (
    FullDataValidationService,
)
from datarecon.application.services.nullability_validation_service import (
    NullabilityValidationService,
)
from datarecon.application.services.record_count_service import (
    RecordCountRequest,
    RecordCountService,
)
from datarecon.application.services.referential_integrity_service import (
    ReferentialIntegrityService,
)
from datarecon.application.services.scheduler_service import (
    NOTIFY_ALWAYS,
    NOTIFY_NEVER,
    SchedulerError,
    SchedulerService,
)
from datarecon.application.services.schema_validation_service import SchemaValidationService
from datarecon.application.services.test_suite_service import (
    TestSuiteService,
    serialize_request,
)
from datarecon.domain.entities.project import Project
from datarecon.domain.enums import RunStatus, ValidationModule
from datarecon.domain.interfaces.notifier import INotifier, Notification
from tests.conftest import FakeExtractionService


class RecordingNotifier(INotifier):
    def __init__(self, succeeds: bool = True):
        self.sent: list[Notification] = []
        self._succeeds = succeeds

    def send(self, notification: Notification) -> bool:
        self.sent.append(notification)
        return self._succeeds


class ExplodingNotifier(INotifier):
    def send(self, notification: Notification) -> bool:
        raise RuntimeError("mail server on fire")


@pytest.fixture
def frames() -> dict[str, pd.DataFrame]:
    return {
        "src": pd.DataFrame({"id": [1, 2, 3]}),
        "tgt": pd.DataFrame({"id": [1, 2, 3]}),
        "tgt_short": pd.DataFrame({"id": [1]}),
    }


@pytest.fixture
def suite_service(
    run_repository, test_suite_repository, project_repository, detail_store, frames
) -> TestSuiteService:
    extraction = FakeExtractionService(frames)
    return TestSuiteService(
        test_suite_repository,
        project_repository,
        SchemaValidationService(extraction, run_repository, detail_store),
        RecordCountService(extraction, run_repository, detail_store),
        DuplicateValidationService(extraction, run_repository, detail_store),
        NullabilityValidationService(extraction, run_repository, detail_store),
        AggregationValidationService(extraction, run_repository, detail_store),
        FullDataValidationService(extraction, run_repository, detail_store),
        ReferentialIntegrityService(extraction, run_repository, detail_store),
    )


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def scheduler(test_suite_repository, suite_service, notifier) -> SchedulerService:
    return SchedulerService(test_suite_repository, suite_service, notifier)


@pytest.fixture
def project(project_repository) -> Project:
    return project_repository.add(Project(name="Scheduled"))


def _save_suite(suite_service, project, name="COUNTS", target="tgt"):
    request = RecordCountRequest(
        source_connection_id="src", target_connection_id=target, name=name
    )
    return suite_service.save_suite(
        project_id=project.project_id,
        name=name,
        module=ValidationModule.RECORD_COUNT,
        config=serialize_request(request),
        source_connection_id="src",
        target_connection_id=target,
    )


# ---------- setting a schedule ----------


def test_set_schedule_stores_the_expression(scheduler, suite_service, project) -> None:
    suite = _save_suite(suite_service, project)

    updated = scheduler.set_schedule(suite.suite_id, "0 6 * * *", enabled=True)

    assert updated.schedule_cron == "0 6 * * *"
    assert updated.schedule_enabled is True


def test_an_invalid_expression_is_rejected_at_save_time(
    scheduler, suite_service, project
) -> None:
    """An unparseable schedule stored as enabled would silently never fire."""
    suite = _save_suite(suite_service, project)

    with pytest.raises(SchedulerError):
        scheduler.set_schedule(suite.suite_id, "not a cron", enabled=True)


def test_enabling_without_an_expression_is_rejected(scheduler, suite_service, project) -> None:
    suite = _save_suite(suite_service, project)

    with pytest.raises(SchedulerError, match="required"):
        scheduler.set_schedule(suite.suite_id, "", enabled=True)


def test_clearing_the_expression_disables_the_schedule(
    scheduler, suite_service, project
) -> None:
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "0 6 * * *", enabled=True)

    updated = scheduler.set_schedule(suite.suite_id, "", enabled=False)

    assert updated.schedule_cron is None
    assert updated.schedule_enabled is False


def test_setting_a_schedule_on_a_missing_suite_raises(scheduler) -> None:
    with pytest.raises(SchedulerError, match="not found"):
        scheduler.set_schedule("nope", "0 6 * * *", enabled=True)


def test_scheduled_suites_lists_schedules_whether_enabled_or_not(
    scheduler, suite_service, project
) -> None:
    a = _save_suite(suite_service, project, name="A")
    b = _save_suite(suite_service, project, name="B")
    _save_suite(suite_service, project, name="C")  # no schedule
    scheduler.set_schedule(a.suite_id, "0 6 * * *", enabled=True)
    scheduler.set_schedule(b.suite_id, "0 7 * * *", enabled=False)

    assert {s.name for s in scheduler.scheduled_suites()} == {"RC_A", "RC_B"}


# ---------- due detection ----------


def test_a_suite_is_due_when_its_cron_matches_the_minute(
    scheduler, suite_service, project
) -> None:
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "30 6 * * *", enabled=True)

    due = scheduler.due_suites(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert [s.suite_id for s in due] == [suite.suite_id]


def test_a_suite_is_not_due_outside_its_minute(scheduler, suite_service, project) -> None:
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "30 6 * * *", enabled=True)

    assert scheduler.due_suites(datetime(2026, 3, 5, 6, 31, tzinfo=UTC)) == []


def test_a_disabled_schedule_never_fires(scheduler, suite_service, project) -> None:
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=False)

    assert scheduler.due_suites(datetime(2026, 3, 5, 6, 30, tzinfo=UTC)) == []


def test_a_suite_already_run_this_minute_is_not_due_again(
    scheduler, suite_service, project, test_suite_repository
) -> None:
    """A tick that runs twice in one minute must not run the suite twice."""
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)
    now = datetime(2026, 3, 5, 6, 30, 40, tzinfo=UTC)
    test_suite_repository.record_run_result(
        suite.suite_id, "run-1", RunStatus.PASS, now.replace(second=5)
    )

    assert scheduler.due_suites(now) == []


def test_a_suite_run_in_the_previous_minute_is_due_again(
    scheduler, suite_service, project, test_suite_repository
) -> None:
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)
    now = datetime(2026, 3, 5, 6, 30, tzinfo=UTC)
    test_suite_repository.record_run_result(
        suite.suite_id, "run-1", RunStatus.PASS, now - timedelta(minutes=1)
    )

    assert [s.suite_id for s in scheduler.due_suites(now)] == [suite.suite_id]


def test_missed_minutes_are_not_caught_up(
    scheduler, suite_service, project, test_suite_repository
) -> None:
    """An hour of downtime must not fire sixty backlogged runs on restart."""
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)
    now = datetime(2026, 3, 5, 7, 30, tzinfo=UTC)
    test_suite_repository.record_run_result(
        suite.suite_id, "run-1", RunStatus.PASS, now - timedelta(hours=1)
    )

    assert len(scheduler.due_suites(now)) == 1


def test_an_unparseable_stored_schedule_does_not_block_the_others(
    scheduler, suite_service, project, test_suite_repository
) -> None:
    good = _save_suite(suite_service, project, name="GOOD")
    broken = _save_suite(suite_service, project, name="BROKEN")
    scheduler.set_schedule(good.suite_id, "* * * * *", enabled=True)
    # Bypass validation to simulate an expression stored by an older version.
    stored = test_suite_repository.get_by_id(broken.suite_id)
    stored.schedule_cron = "nonsense"
    stored.schedule_enabled = True
    test_suite_repository.update(stored)

    due = scheduler.due_suites(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert [s.suite_id for s in due] == [good.suite_id]


def test_schedules_are_read_in_the_configured_timezone(
    test_suite_repository, suite_service, notifier, project
) -> None:
    """06:00 in Kolkata is 00:30 UTC — the point of the setting."""
    scheduler = SchedulerService(
        test_suite_repository, suite_service, notifier, timezone="Asia/Kolkata"
    )
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "0 6 * * *", enabled=True)

    assert scheduler.due_suites(datetime(2026, 3, 5, 0, 30, tzinfo=UTC))
    assert not scheduler.due_suites(datetime(2026, 3, 5, 6, 0, tzinfo=UTC))


def test_an_unknown_timezone_falls_back_to_utc(
    test_suite_repository, suite_service, notifier
) -> None:
    scheduler = SchedulerService(
        test_suite_repository, suite_service, notifier, timezone="Mars/Olympus_Mons"
    )
    assert scheduler.timezone_name == "UTC"


# ---------- ticks ----------


def test_tick_runs_every_due_suite(scheduler, suite_service, project) -> None:
    a = _save_suite(suite_service, project, name="A")
    b = _save_suite(suite_service, project, name="B")
    for suite in (a, b):
        scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)

    result = scheduler.tick(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert {o.suite.name for o in result.outcomes} == {"RC_A", "RC_B"}
    assert all(o.status == RunStatus.PASS for o in result.outcomes)


def test_tick_with_nothing_due_runs_nothing_and_notifies_nobody(
    scheduler, suite_service, project, notifier
) -> None:
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "0 6 * * *", enabled=True)

    result = scheduler.tick(datetime(2026, 3, 5, 9, 0, tzinfo=UTC))

    assert result.ran_nothing
    assert notifier.sent == []


def test_a_failing_suite_notifies(scheduler, suite_service, project, notifier) -> None:
    suite = _save_suite(suite_service, project, name="SHORT", target="tgt_short")
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)

    result = scheduler.tick(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert [o.status for o in result.outcomes] == [RunStatus.FAIL]
    assert len(notifier.sent) == 1
    assert notifier.sent[0].is_failure is True
    assert "RC_SHORT" in notifier.sent[0].body
    assert result.notification_sent is True


def test_a_passing_suite_does_not_notify_under_the_default_policy(
    scheduler, suite_service, project, notifier
) -> None:
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)

    scheduler.tick(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert notifier.sent == []


def test_notify_always_reports_successes_too(
    test_suite_repository, suite_service, notifier, project
) -> None:
    scheduler = SchedulerService(
        test_suite_repository, suite_service, notifier, notify_on=NOTIFY_ALWAYS
    )
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)

    scheduler.tick(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert len(notifier.sent) == 1
    assert notifier.sent[0].is_failure is False
    assert "passed" in notifier.sent[0].subject


def test_notify_never_stays_silent_on_failure(
    test_suite_repository, suite_service, notifier, project
) -> None:
    scheduler = SchedulerService(
        test_suite_repository, suite_service, notifier, notify_on=NOTIFY_NEVER
    )
    suite = _save_suite(suite_service, project, name="SHORT", target="tgt_short")
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)

    result = scheduler.tick(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert result.failures
    assert notifier.sent == []


def test_the_failure_message_carries_the_run_summary(
    scheduler, suite_service, project, notifier
) -> None:
    """An alert that sends you back to the app to learn anything is barely an alert."""
    suite = _save_suite(suite_service, project, name="SHORT", target="tgt_short")
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)

    scheduler.tick(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    body = notifier.sent[0].body
    assert "source_count" in body and "target_count" in body


def test_a_notifier_that_reports_failure_leaves_the_runs_intact(
    test_suite_repository, suite_service, project
) -> None:
    scheduler = SchedulerService(
        test_suite_repository, suite_service, RecordingNotifier(succeeds=False)
    )
    suite = _save_suite(suite_service, project, name="SHORT", target="tgt_short")
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)

    result = scheduler.tick(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert result.notification_sent is False
    assert [o.status for o in result.outcomes] == [RunStatus.FAIL]


def test_a_naive_last_run_timestamp_is_read_as_utc(
    scheduler, suite_service, project, test_suite_repository
) -> None:
    """Reading it as machine-local time would shift the schedule by the offset."""
    suite = _save_suite(suite_service, project)
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)
    now = datetime(2026, 3, 5, 6, 30, tzinfo=UTC)
    test_suite_repository.record_run_result(
        suite.suite_id, "run-1", RunStatus.PASS, datetime(2026, 3, 5, 6, 30, 10)
    )

    assert scheduler.due_suites(now) == []


def test_next_runs_uses_the_schedulers_timezone(scheduler) -> None:
    runs = scheduler.next_runs("0 6 * * *", 2)
    assert len(runs) == 2
    assert all(r.hour == 6 and r.minute == 0 for r in runs)


def test_next_runs_rejects_an_invalid_expression(scheduler) -> None:
    with pytest.raises(SchedulerError):
        scheduler.next_runs("* * *", 1)


def test_a_notifier_that_raises_does_not_lose_the_tick(
    test_suite_repository, suite_service, project
) -> None:
    scheduler = SchedulerService(test_suite_repository, suite_service, ExplodingNotifier())
    suite = _save_suite(suite_service, project, name="SHORT", target="tgt_short")
    scheduler.set_schedule(suite.suite_id, "* * * * *", enabled=True)

    result = scheduler.tick(datetime(2026, 3, 5, 6, 30, tzinfo=UTC))

    assert result.notification_sent is False
    assert [o.status for o in result.outcomes] == [RunStatus.FAIL]
