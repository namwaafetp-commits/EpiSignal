# Local Telegram cadence correction report

## Scope and result

Repository-only documentation and regression tests, based on `d513abb0877fb4990145a6221123c080fb216999`, on `codex/next-iteration`.
Work used `C:\Users\DELL\EpiSignal` because the supplied D: workspace was unavailable.
The corrected scheduler design is **PROPOSED — NOT INSTALLED**.
No runtime implementation, deployment file, scheduler script, or migration changed.

## Root cause and proposed design

With synthetic hourly starts at :00 and completion at :06, five-minute polling
observes 08:35 freshness 29m (HEALTHY), 08:40 freshness 34m (WARNING), 09:05
freshness 59m (WARNING), and 09:10 freshness 4m (HEALTHY/recovery). The regression
reproduces three routine WARNING/recovery pairs over three hours.

**IMPLEMENTED IN CODE:** regression tests call the existing evaluator and
notification service, with Telegram mocked and real temporary SQLite state.
The notification implementation, state machine, and one-second lock timeout
are retained unchanged.

**PROPOSED FOR PRODUCTION DEPLOYMENT:** evaluate after the scheduled wrapper
finishes, preserving its original exit status and isolating notification failures.
Independent watchdog invocations at :16/:26 detect absent or stalled wrappers.
Daily reporting uses 08:20 ICT / 01:20 UTC, with a bounded eligible retry at
08:21 ICT / 01:21 UTC. Existing daily-date deduplication suppresses a second
successful report. Periodic modes have no shared scheduled minute.
All scheduler entries are **PROPOSED — NOT INSTALLED**; exact snippets are in
[the deployment proposal](../telegram-monitoring.md).

**TO VERIFY DURING DEPLOYMENT:** minute-00 phase and ordinary completion before
minute 15 are assumptions, not production measurements. Normal synthetic
runtimes of 0.1, 6, and 14.9 minutes produce no freshness alerts at proposed times.
Adjust the proposed clock times after verifying the actual phase/runtime.

## Missed-run and concurrency evidence

Skipping the 08:00 run leaves latest completion 07:06; at 08:16 freshness is
70 minutes and the unchanged evaluator returns CRITICAL. A still-running late
run also becomes CRITICAL despite healthy active-run coverage. Tests preserve
stage WARNING/CRITICAL delivery, retry, deduplication, and one recovery once the
overall result is HEALTHY. A genuinely missing slot can keep calendar-day
coverage abnormal until Bangkok midnight; later freshness alone is not recovery.

SQLite still serializes comparison, send, and checkpoint with BEGIN IMMEDIATE
and a one-second wait. Real overlapping daily/alert transactions are tested in
both directions: the loser sends nothing, leaves its checkpoint eligible, then
succeeds on retry and deduplicates. Removing intentional scheduling collisions
is sufficient for this best-effort proposal; late/manual overlap remains possible.
Daily :21 and watchdog :26 provide later eligible attempts. No delivery guarantee
or exactly-once external send is claimed. No persistence redesign was needed.

## Deployment verification checklist

**TO VERIFY ON VPS DURING DEPLOYMENT** — none verified in this task:

- Actual production cron, hourly phase, runtime, wrapper success/failure/timeout paths.
- Actual API container name and timeout command availability.
- Server and cron timezone.
- Writable persistent notification directory and UID/GID ownership.
- Coolify bot/chat/state-path environment variables.
- Durable notification state mount shared by all invocations and surviving replacement.
- No duplicate scheduler entries or superseded five-minute polling job.
- Notification failure preserves the surveillance command's original exit status.

## Local validation

- Notification and monitoring tests (eight test modules): **150 passed**, exit 0.
- New cadence plus notification/state suites: **40 passed in 6.81s**.
- Backend: `uv run pytest packages/backend/tests -q -rs`, exit 0;
  **1,360 passed, 2 skipped** (1,362 collected; quiet output showed two skips).
- Skips: `test_ai_repository_postgresql.py` and `test_read_only_transaction.py`,
  because `EPISIGNAL_TEST_DATABASE_URL` is not configured. No production DB used.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 303 files already formatted.
- `corepack pnpm verify`: **exit 0**. Actual gate output excerpts:

```text
303 files already formatted
All matched files use Prettier code style!
All checks passed!
Success: no issues found in 145 source files
Test Files  14 passed (14)
Tests  107 passed (107)
1432 passed, 2 skipped, 2 warnings in 44.92s
wrote openapi.json
Compiled successfully in 737ms
Generating static pages using 8 workers (6/6) in 790ms
```

The gate includes web/Python formatting, lint, TypeScript/mypy, all tests,
contract regeneration/diff, and production web build. Two Python warnings are
existing Starlette deprecations. Contract generation produced only checkout
line-ending noise; an empty content diff was confirmed and that generated file
restored. No contract change is included. Subsequent edits only record this
validation in Markdown; no tested source, tests, or schedule changed.

Independent standards review: **no actionable findings**.
Independent specification review: **no actionable findings** (37 focused tests passed).

## Files changed

- `docs/telegram-monitoring.md`: corrected proposed cadence, failure boundary, checklist, concurrency limits.
- `packages/backend/tests/test_notification_cadence.py`: ten synthetic evaluator/notification cases.
- `packages/backend/tests/test_monitoring_notifications.py`: two real SQLite overlap cases.
- `docs/reports/2026-09-07-telegram-monitoring-report.md`: historical scheduling supersession notice.
- `STATUS.md`: completion ledger.
- This report: local evidence and deployment limits.

## Invariants and Git handoff

No monitoring health semantics changed.
No thresholds changed.
No AI behavior changed.
No surveillance pipeline behavior changed.
No Alembic migration added.
Expected Alembic head: `20260904_0022` (local `alembic heads` confirmed).

Branch: `codex/next-iteration`. Final commit/push/clean-tree evidence is provided
in the task response after this report is committed. GitHub is the only remote
used; no production access was attempted.

```text
NOT DEPLOYED
VPS NOT ACCESSED
COOLIFY NOT ACCESSED
PRODUCTION CRON NOT MODIFIED
```
