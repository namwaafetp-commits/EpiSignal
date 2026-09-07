# Telegram monitoring implementation plan

**Goal:** Deliver the user-specified deterministic daily report, abnormal transitions,
and recovery notifications on `codex/next-iteration`, for review without deployment.

**Architecture:** `monitoring_runner` loads the existing `HealthSummary` once in a
read-only transaction. Notification formatters consume its values and statuses.
A small Telegram transport sends plain text. A local SQLite notification-state
file on an explicitly configured durable mount serializes sends and preserves
last delivered incident fingerprints and daily dates. No surveillance schema or
pipeline changes are needed. Existing models contain no general monitoring state
store; pipeline run records and domain-specific state are unsuitable for this.

**Tech stack:** Existing Python 3.12, Pydantic settings, stdlib HTTPS and SQLite,
pytest, Ruff, mypy, and the repository pnpm verification gate.

The attached user specification supplies the approved architecture, acceptance
criteria, test seams, and authorization to implement, commit, and push.

## Ordered work

- [x] Establish the existing monitoring test baseline; retain evaluator semantics.
- [x] Add a mocked HTTPS transport test, observe failure, implement bounded
  secret-safe delivery, then exercise HTTP/API/network/disabled paths.
- [x] Add deterministic formatter tests, observe failure, implement reports from
  `HealthSummary`. Label coverage as current Bangkok day and other metrics as
  trailing 24 hours. `latest_run` means latest completion, not scheduled start;
  omit unavailable scheduled-start time. Reuse evaluator threshold constants.
- [x] Add persisted transition tests, observe failure, implement serialized SQLite
  state for incident identity/severity and daily date. Commit delivered state only
  after acknowledgement; retain failed transitions for the next observation.
  Suppress stale snapshots and unchanged fingerprints. No volatile numeric keys.
  Keep observed status separate from acknowledgement; a failed recovery must not
  suppress a recurrence, and failed condition B must not hide a return to A.
- [x] Test and integrate opt-in `--notify`, `--daily-report`, and
  `--telegram-smoke-test` modes on the monitoring command. No flags preserve the
  original read-only JSON path. Catch errors separately with safe log event names.
- [x] Document environment, writable durable mount, 08:00 Bangkok / 01:00 UTC
  daily cron, proposed periodic monitoring-only cron, disable and smoke test.
- [x] Independently review standards and specification against baseline
  `1a0c8045d25aeff3fd6ba2c7d12ffa946fa7b4bd`; resolve actionable findings.
- [x] Run monitoring/notification/backend tests and `corepack pnpm verify`; record
  exact results and Alembic head in a completion report and STATUS ledger.
  The existing web marker test resets the fixture clock to real time; pin Date
  while keeping async timers real so validation works after the fixture ages.
- [x] Commit and push `codex/next-iteration`. Do not deploy, touch VPS, run
  production migrations, requeue, backfill, change AI behavior, or run surveillance.

## Delivery limits for review

SQLite uses a local durable filesystem, shared by every notification invocation.
No PostgreSQL/Alembic migration is introduced. A process crash after Telegram
accepts a message but before committing state can duplicate the message on the
next invocation; Telegram offers no sendMessage idempotency key. Failed sends
retry only on a later scheduled invocation, never in an unbounded loop.
