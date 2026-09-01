# datarecon/scheduler.py — the unattended runner (ADR-0014).
#
#   python -m datarecon.scheduler            # tick every minute until stopped
#   python -m datarecon.scheduler --once     # one tick, for OS cron/Task Scheduler
#   python -m datarecon.scheduler --list     # show what is scheduled, and when
#
# This is a separate process on purpose. A Streamlit server only runs code
# while a browser session is driving it, so a thread inside the app would fire
# schedules only while somebody happened to be watching — which is the one
# condition under which unattended execution is not needed.
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

from config.settings import settings
from datarecon.application.services.scheduler_service import SchedulerService, TickResult
from datarecon.bootstrap import build_container

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
logger = logging.getLogger("datarecon.scheduler")


def build_scheduler() -> SchedulerService:
    """Wire the scheduler from the same composition root the app uses."""
    return build_container().scheduler_service


def _log_tick(result: TickResult) -> None:
    if result.ran_nothing:
        logger.debug("Nothing due at %s", result.checked_at.isoformat(timespec="minutes"))
        return
    for outcome in result.outcomes:
        message = f"{outcome.status.value:5} {outcome.suite.name}"
        if outcome.error_message:
            message += f" — {outcome.error_message}"
        logger.log(logging.WARNING if outcome.status.value != "PASS" else logging.INFO, message)
    if result.failures and not result.notification_sent:
        logger.warning("Failures were not notified — no channel configured or delivery failed.")


def _print_schedules(scheduler: SchedulerService) -> int:
    suites = scheduler.scheduled_suites()
    if not suites:
        print("No test suites have a schedule. Add one on the Test Suites page.")
        return 0

    print(f"Schedules are read in {scheduler.timezone_name}.\n")
    for suite in sorted(suites, key=lambda s: s.name):
        state = "enabled " if suite.schedule_enabled else "disabled"
        print(f"[{state}] {suite.name:40} {suite.schedule_cron}")
        try:
            upcoming = scheduler.next_runs(suite.schedule_cron or "", 3)
            for moment in upcoming:
                print(f"             next: {moment:%Y-%m-%d %H:%M}")
        except Exception as exc:
            print(f"             invalid schedule: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m datarecon.scheduler",
        description="Run scheduled DataRecon test suites unattended.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one tick and exit — use this when OS cron drives the schedule.",
    )
    parser.add_argument(
        "--list", action="store_true", help="Show scheduled suites and their next run times."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=settings.scheduler_interval_seconds,
        help="Seconds between ticks in the default loop mode (default: %(default)s).",
    )
    parser.add_argument("--verbose", action="store_true", help="Log every tick, including idle ones.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format=_LOG_FORMAT
    )
    scheduler = build_scheduler()

    if args.list:
        return _print_schedules(scheduler)

    if args.once:
        _log_tick(scheduler.tick(datetime.now(UTC)))
        return 0

    interval = max(1, args.interval)
    logger.info(
        "Scheduler started — checking every %ss, schedules read in %s.",
        interval,
        scheduler.timezone_name,
    )
    try:
        while True:
            try:
                _log_tick(scheduler.tick(datetime.now(UTC)))
            except Exception:
                # One bad tick must not end the daemon; the next minute may
                # well succeed, and a dead scheduler fails silently forever.
                logger.exception("Scheduler tick failed")
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
