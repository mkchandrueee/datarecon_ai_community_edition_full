# ADR-0014: Scheduling runs in a separate process, not inside Streamlit

## Status
Accepted — supersedes the deferral in ADR-0005 ("no code reads
`schedule_cron` / `schedule_enabled`"). The fields it reserved are now read.

## Context
Saved Test Suites made regression checks repeatable, but only while someone
was sitting in front of the app. The value of a reconciliation check is
largely in catching a bad load before anyone looks — which means running on a
schedule and telling a person when it breaks.

ADR-0002 rules out the Enterprise scheduling stack (Celery, a broker,
Kubernetes) for Community Edition, so the question was where the schedule
actually executes.

**A background thread inside the Streamlit server** was rejected. Streamlit
runs script code in response to browser sessions; a thread started from a
script run is tied to a server that reloads on every file change and is
restarted casually. Worse, the failure mode is silent: schedules appear
configured and simply never fire. It would also fire only while somebody had
the app open — the exact condition under which unattended execution is not
needed.

**A cron library** (`croniter`, APScheduler) was rejected for a different
reason: the useful subset of cron is five fields with wildcards, lists,
ranges and steps. That is about a hundred lines, is exactly testable, and
avoids adding a dependency to an install that already carries a large driver
matrix.

## Decision
- `datarecon/core/cron.py` parses and matches five-field cron expressions —
  `*`, `a`, `a,b`, `a-b`, `*/n`, `a-b/n`, month and day names, `7` as Sunday,
  and the `@daily`-style presets. Both day fields restricted means OR, as in
  Vixie cron. `next_runs()` exists so the UI can show what an expression means
  before it is saved.
- **`python -m datarecon.scheduler` is a separate process.** It ticks once a
  minute by default; `--once` makes it a single tick so OS cron or Windows
  Task Scheduler can drive it instead; `--list` prints what is scheduled and
  when it next fires. A failing tick is logged and the loop continues — a
  scheduler that dies on one bad run fails silently forever.
- The composition root moved from `app.py` to `datarecon/bootstrap.py` so the
  daemon builds the *same* object graph as the UI rather than a second, subtly
  different one. `app.py` keeps a `@st.cache_resource` wrapper over it.
- **Missed minutes are not caught up.** A scheduler that was down for an hour
  must not fire sixty backlogged runs on restart; the point of a schedule is a
  run at a time, not a queue of stale ones. Due-ness is therefore "the cron
  matches this minute and the suite has not already run within it", which needs
  no new schema column and is idempotent under a tick that runs twice.
- **Schedules are read in a configurable zone** (`DATARECON_SCHEDULE_TZ`,
  default UTC) while runs stay stored in UTC. Cron means local time to the
  person writing it; making them convert to UTC in their head is how a report
  ends up running at 11:30pm.
- Notifications go through an `INotifier` port with SMTP-email and
  webhook (Slack/Teams) adapters, both standard-library only. **A notifier
  never raises**: the run result is already recorded, and losing it to a mail
  outage would be the worse failure. Transport errors are collected on the
  notifier instead. No channel configured is a valid installation.
- Credentials come from the environment, never the metadata database — a
  scheduled job's mail password is deployment configuration, and the metadata
  file gets copied between machines.
- Default policy is notify **on failure**; `DATARECON_NOTIFY_ON=always` covers
  the "prove it ran" case. The message carries the failing run's summary
  metrics, not just a status line — an alert that sends you back to the app to
  learn anything is barely an alert.

## Consequences
- Scheduling works with no new infrastructure: one Python process, or an entry
  in the cron table already on the box.
- The schedule only fires while that process is running. This is visible rather
  than silent — `--list` shows the schedule and the Test Suites page shows last
  run status — but it is genuinely on the operator to keep it alive.
- Cron's resolution is one minute, and a tick that takes longer than a minute
  delays the following one. Long-running suites can therefore drift; they will
  not overlap or double-fire.
- The cron subset is ours, so anything beyond it (`L`, `W`, `#`, seconds) is
  unsupported and rejected at save time rather than silently misread.
