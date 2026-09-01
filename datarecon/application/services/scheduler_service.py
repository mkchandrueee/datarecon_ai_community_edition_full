# datarecon/application/services/scheduler_service.py
# Unattended execution of saved Test Suites on a cron schedule, with a
# notification when something breaks (ADR-0014). ADR-0005 reserved
# `schedule_cron` / `schedule_enabled` on TestSuite for exactly this; nothing
# read them until now.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from datarecon.application.services.test_suite_service import (
    TestSuiteRunOutcome,
    TestSuiteService,
)
from datarecon.core.cron import CronError, CronSchedule
from datarecon.domain.entities.test_suite import TestSuite
from datarecon.domain.enums import RunStatus
from datarecon.domain.interfaces.notifier import INotifier, Notification
from datarecon.domain.interfaces.test_suite_repository import ITestSuiteRepository

#: Statuses worth waking someone up for.
_FAILING = frozenset({RunStatus.FAIL, RunStatus.ERROR})

NOTIFY_ON_FAILURE = "failure"
NOTIFY_ALWAYS = "always"
NOTIFY_NEVER = "never"


class SchedulerError(ValueError):
    """Raised for an invalid schedule."""


@dataclass
class TickResult:
    """What one scheduler tick did, so a runner can log it and tests can read it."""

    checked_at: datetime
    due: list[TestSuite] = field(default_factory=list)
    outcomes: list[TestSuiteRunOutcome] = field(default_factory=list)
    notification_sent: bool = False

    @property
    def failures(self) -> list[TestSuiteRunOutcome]:
        return [o for o in self.outcomes if o.status in _FAILING]

    @property
    def ran_nothing(self) -> bool:
        return not self.outcomes


class SchedulerService:
    def __init__(
        self,
        repository: ITestSuiteRepository,
        test_suite_service: TestSuiteService,
        notifier: INotifier,
        timezone: str = "UTC",
        notify_on: str = NOTIFY_ON_FAILURE,
    ):
        self._repo = repository
        self._suites = test_suite_service
        self._notifier = notifier
        self._timezone_name = timezone
        self._notify_on = (notify_on or NOTIFY_ON_FAILURE).strip().casefold()

    # ---------- schedule management ----------
    @property
    def timezone(self) -> ZoneInfo:
        """The zone cron expressions are read in.

        An unknown zone name falls back to UTC rather than crashing the app:
        a typo in an environment variable should not take the tool down, and
        the UI shows which zone is actually in effect.
        """
        try:
            return ZoneInfo(self._timezone_name)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            return ZoneInfo("UTC")

    @property
    def timezone_name(self) -> str:
        return str(self.timezone)

    @staticmethod
    def parse(cron_expression: str) -> CronSchedule:
        try:
            return CronSchedule.parse(cron_expression)
        except CronError as exc:
            raise SchedulerError(str(exc)) from exc

    def next_runs(self, cron_expression: str, count: int = 3) -> list[datetime]:
        """Upcoming fire times, in the schedule's own zone."""
        schedule = self.parse(cron_expression)
        return schedule.next_runs(datetime.now(self.timezone), count)

    def set_schedule(
        self, suite_id: str, cron_expression: str | None, enabled: bool
    ) -> TestSuite:
        """Attach (or clear) a schedule on a suite.

        A schedule is validated before it is stored — an expression that cannot
        be parsed would otherwise sit enabled and silently never fire, which is
        the worst outcome for something meant to run unattended.
        """
        suite = self._repo.get_by_id(suite_id)
        if suite is None:
            raise SchedulerError(f"Test suite '{suite_id}' not found.")

        expression = (cron_expression or "").strip()
        if enabled and not expression:
            raise SchedulerError("A cron expression is required to enable a schedule.")
        if expression:
            self.parse(expression)

        suite.schedule_cron = expression or None
        suite.schedule_enabled = bool(enabled and expression)
        suite.touch()
        return self._repo.update(suite)

    def scheduled_suites(self) -> list[TestSuite]:
        """Every suite carrying a schedule, enabled or not."""
        return [s for s in self._repo.list_all() if s.schedule_cron]

    # ---------- execution ----------
    def due_suites(self, now: datetime | None = None) -> list[TestSuite]:
        """Enabled suites whose cron matches this minute and that haven't run in it.

        Missed minutes are not caught up. A scheduler that was down for an hour
        should not fire sixty backlogged runs the moment it returns — the point
        of a schedule is a run at a time, not a queue of stale ones.
        """
        moment = _as_utc(now or datetime.now(UTC))
        minute_start = moment.replace(second=0, microsecond=0)
        local = moment.astimezone(self.timezone)

        due: list[TestSuite] = []
        for suite in self._repo.list_all():
            if not (suite.schedule_enabled and suite.schedule_cron):
                continue
            try:
                schedule = CronSchedule.parse(suite.schedule_cron)
            except CronError:
                # A stored expression that no longer parses is skipped rather
                # than allowed to abort every other suite's schedule.
                continue
            if not schedule.matches(local):
                continue
            last_run = _as_utc(suite.last_run_at) if suite.last_run_at else None
            if last_run is not None and last_run >= minute_start:
                continue
            due.append(suite)
        return due

    def tick(self, now: datetime | None = None) -> TickResult:
        """Run everything due at `now` and notify once for the whole tick."""
        moment = _as_utc(now or datetime.now(UTC))
        due = self.due_suites(moment)
        result = TickResult(checked_at=moment, due=due)
        if not due:
            return result

        result.outcomes = self._suites.run_suites([s.suite_id for s in due])
        if self._should_notify(result):
            try:
                result.notification_sent = self._notifier.send(self._build_notification(result))
            except Exception:
                # The adapters swallow their own transport errors, but a
                # notifier is replaceable — and no notifier is worth losing an
                # already-completed tick's results over.
                result.notification_sent = False
        return result

    # ---------- notification ----------
    def _should_notify(self, result: TickResult) -> bool:
        if self._notify_on == NOTIFY_NEVER or result.ran_nothing:
            return False
        if self._notify_on == NOTIFY_ALWAYS:
            return True
        return bool(result.failures)

    def _build_notification(self, result: TickResult) -> Notification:
        failures = result.failures
        when = result.checked_at.astimezone(self.timezone).strftime("%Y-%m-%d %H:%M %Z")

        if failures:
            subject = f"DataRecon: {len(failures)} of {len(result.outcomes)} scheduled suite(s) failed"
        else:
            subject = f"DataRecon: {len(result.outcomes)} scheduled suite(s) passed"

        lines = [f"Scheduled run at {when}", ""]
        for outcome in result.outcomes:
            line = f"  [{outcome.status.value}] {outcome.suite.name} ({outcome.suite.module.value})"
            if outcome.error_message:
                line += f" - {outcome.error_message}"
            lines.append(line)

        # The summary of a failure is the whole reason to open the email; a
        # status line alone sends the reader back to the app to learn nothing.
        for outcome in failures:
            if outcome.run and outcome.run.summary:
                lines.append("")
                lines.append(f"{outcome.suite.name}:")
                lines.extend(f"  {k}: {v}" for k, v in outcome.run.summary.items())

        return Notification(subject=subject, body="\n".join(lines), is_failure=bool(failures))


def _as_utc(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC rather than as machine-local time.

    Everything this codebase writes is timezone-aware UTC; a naive value can
    only come from older data, and reading it as local time would shift a
    schedule by the machine's offset.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
