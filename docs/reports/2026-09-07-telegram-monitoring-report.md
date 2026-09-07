# Telegram monitoring implementation report

## 1. Summary

Implemented deterministic daily health reports, WARNING/CRITICAL transition
alerts, persisted duplicate suppression, and recovery notifications. All consume
the existing evaluator. No AI interpretation, remediation, pipeline execution,
requeue, backfill, production configuration change, or deployment was performed.

The supplied D: workspace was unavailable. Work was completed in a fresh local
checkout at `C:\Users\DELL\EpiSignal` on the requested existing branch.

## 2. Architecture

- `monitoring_runner.py`: extracts the existing read-only evaluation into
  `load_health_summary()`, then exposes three mutually exclusive notification modes.
- `monitoring_messages.py`: deterministic daily, abnormal, recovery, and stable
  abnormal fingerprint formatting from `HealthSummary`.
- `telegram.py`: small stdlib HTTPS transport; masked settings, 10-second socket
  timeout, bounded response reads, no redirects or immediate retries.
- `notification_state.py`: SQLite transaction and durable checkpoints.
- `monitoring_notifications.py`: observed-state comparison, delivery, recovery,
  retry-on-next-observation, daily-date deduplication, and sanitized logs.
- `config.py`: three optional Telegram settings; rejects relative state paths.
- `operational_monitoring.py`: extracts existing literal freshness/runtime/fatal
  thresholds into shared constants, with identical values and comparisons.

`SqlAlchemyPipelineHealthRepository`, `pipeline_runs` coverage reads, stage-count
telemetry, evaluator output schema, and surveillance execution remain unchanged.

## 3. Daily report

Command: `python -m episignal_backend.monitoring_runner --daily-report`.
Data source: the normal read-only monitoring query and one `summarize_health()`
evaluation. Coverage is current Bangkok day; other summary metrics use trailing
24 hours. The example below is rendered from a synthetic test fixture, not
production observations:

```text
🟢 EpiSignal Daily Health
6 Sep 2026 (ICT)

Pipeline (coverage: current ICT day; output and runs: trailing 24h)
✓ Coverage: 100% (9 scheduled slots due today)
✓ Run success: 1/1 (100%)
✓ Freshness: 0m
✓ p95 runtime: 5m
✓ Fatal errors: 0
✓ Last completed run: 6 Sep 2026 08:05 ICT

Stages
✓ DeepSeek: 100% (healthy ≥99%)
✓ Retrieval: 100% (healthy ≥95%)
✓ Gemini: 100% (healthy ≥98%)
✓ Grouping: 100% (healthy ≥99%)
✓ Mistral: 100% (healthy ≥98%)

24h Output
Discovered: 12
Relevant: 0
New events: 1
Updated events: 2
Summarized events: 3

Recent failures
None

Overall: HEALTHY
```

Proposed schedule: 08:00 Asia/Bangkok, corresponding to 01:00 UTC. A successful
daily send is persisted per Bangkok date. No cron was installed or changed.
The latest scheduled start is unavailable in `HealthSummary`; the available
latest completion is labeled accurately instead.

## 4. Abnormal alerts

`python -m episignal_backend.monitoring_runner --notify` evaluates alerts after
the existing snapshot is produced and JSON is emitted. It sends on the first
observing evaluation. Proposed cadence is every five minutes, independently of
the surveillance pipeline, or adding `--notify` to an existing operator-managed
monitoring job.

Fingerprint: overall severity plus sorted abnormal metric/stage identities and
their evaluator-provided statuses. No numeric values, time, or failure samples
enter the fingerprint. GREEN remains quiet; unchanged abnormal states are
suppressed; severity changes and changed conditions alert. Escalation sends a new
alert. WARNING/CRITICAL to HEALTHY sends one recovery. NEUTRAL never claims recovery.

Observed state is persisted separately from acknowledgement. Failed recovery
does not hide a later recurrence; failed condition B does not hide a return to A.
Failed sends retry only on a later invocation. A newer abnormal state supersedes
a pending recovery. Older snapshots cannot roll back newer state.

## 5. Persistence

SQLite file at the configured absolute `EPISIGNAL_TELEGRAM_STATE_PATH`, proposed
as `/var/lib/episignal-notifications/state.sqlite3` on a persistent local bind mount.
The parent directory must exist and be writable by container UID/GID 10001.

The private `notification_state` table stores channel/destination hash, delivery
checkpoint, observed timestamp, observed fingerprint/status, and pending recovery
severity. It stores no message bodies, tokens, chat IDs, or failure telemetry.
Daily and alert channels are independent. SQLite serializes comparison/send/write
across processes with a one-second lock timeout.

No Alembic migration was required. Existing domain/telemetry tables contain no
suitable generic monitoring checkpoint store; a minimal local file avoids adding
notification state to the surveillance database.

## 6. Telegram configuration

- `EPISIGNAL_TELEGRAM_BOT_TOKEN` (masked)
- `EPISIGNAL_TELEGRAM_CHAT_ID` (masked)
- `EPISIGNAL_TELEGRAM_STATE_PATH` (absolute durable file path)

Blank bot/chat settings disable sends. Daily/alert modes also require state path.
No secrets are committed or included in this report.

## 7. Failure safety

Telegram HTTP/API/network failures return a delivery failure and log no exception
text, response body, token-bearing URL, chat ID, or message payload. No immediate
retry loop is added. Configuration absence is explicit and nonfatal.

Monitoring evaluation failure returns exit 1, sends nothing, and preserves state.
Successful monitoring with failed alert delivery still exits 0 and emits the
same health JSON. Daily/smoke delivery failures exit 1. Process restarts reopen
durable state; corrupt/unwritable/locked state prevents sends and logs separately.

Telegram failure cannot make the surveillance pipeline fail: notification code is
invoked only by the separate monitoring CLI. All Telegram tests use mocked HTTP;
the static smoke command was tested with mocks, not sent to a real chat.

## 8. Tests

Validation on 7 September 2026, tested source tree committed as `a053e19`:

| Check | Result |
| --- | --- |
| New notification test files | 57 passed |
| Monitoring evaluator/repository/runner suites | 81 passed (73 original + 8 orchestration tests) |
| Combined monitoring/notification tests | 138 passed |
| Backend tests within full Python run | 1,348 passed, 2 skipped (1,350 collected) |
| Full Python suite | 1,418 passed, 2 skipped, 2 warnings |
| Web tests | 107 passed, 14 files |
| `corepack pnpm verify` | PASS, exit 0 |
| Ruff / ESLint / formatting | PASS; 302 Python files formatted |
| mypy / TypeScript | PASS; 145 Python source files |
| Contract regeneration/diff check | PASS; no contract content changes |
| Next.js production build | PASS |
| `git diff --check` | PASS |

Actual gate output excerpts:

```text
302 files already formatted
All matched files use Prettier code style!
All checks passed!
Success: no issues found in 145 source files
Test Files  14 passed (14)
Tests  107 passed (107)
1418 passed, 2 skipped, 2 warnings in 68.63s (0:01:08)
Compiled successfully in 11.4s
Generating static pages using 8 workers (6/6) in 859ms
```

After the absolute-path validation change, Ruff, formatting, mypy, and the full
138-test focused suite were checked again. Both skipped tests require
`EPISIGNAL_TEST_DATABASE_URL`; no production DB was used as a substitute. Existing
Starlette deprecations and Vite configuration warnings remain.

Explicit transition coverage: GREEN→GREEN, GREEN→WARNING, GREEN→CRITICAL,
WARNING→WARNING, WARNING→CRITICAL, CRITICAL→CRITICAL, CRITICAL→WARNING,
WARNING→GREEN, CRITICAL→GREEN, WARNING(A)→WARNING(B), repeated GREEN, restart,
failed alert retry, failed recovery retry, recurrence after failed recovery,
failed B→A, and stale snapshots. Daily-date dedup, Bangkok midnight, independent
daily/alert state, SQLite rollback/locking/corruption, and real subprocess restart
are tested. Formatter tests cover healthy/WARNING/CRITICAL, N/A, zero relevant,
missing stages, bounded retrieval/Mistral failures, and fractional percentages.

The first full gate exposed an existing web test that restored the real clock
and aged its fixed fixture out of the dashboard window. A three-line test-only
fix pins Date while retaining real async timers. Production map code is unchanged.

## 9. Monitoring semantics verification

**No monitoring health semantics changed.** Thresholds, denominators, stage
success definitions, and coverage semantics are unchanged. Zero relevant remains
valid; zero denominator remains N/A; coverage remains based on scheduled
`pipeline_runs`; manual runs do not count toward coverage; Gemini remains
signal-level; expected retrieval terminal states remain successful; empty
`recent_failures = {}` remains valid. Existing monitoring tests pass unchanged.

## 10. Database/migrations

- Alembic migration added: no.
- Expected Alembic head: `20260904_0022`.
- Private SQLite checkpoint table initialized locally when notifications run.
- No production migrations executed.

## 11. Documentation

Updated README and `.env.production.example`; added `docs/telegram-monitoring.md`,
an optional `docker-compose.monitoring.example.yaml`, implementation plan, this
report, and the STATUS ledger. The optional compose file is not included by the
default deployment. Operator instructions cover BotFather/chat ID, safe static
smoke test, schedule/timezone, durable state ownership, disable, and rollback.

## 12. Git

Branch: `codex/next-iteration`.
Implementation commit: `a053e19af26440df819e447a0297e601ea20d1fb`.
This report and ledger are recorded in a subsequent documentation commit.
Final remote push confirmation is supplied in the task response.

## 13. Deployment

**NOT DEPLOYED**

No VPS/Coolify/production cron edits, production migrations, manual surveillance
runs, requeues, backfills, or live Telegram sends were performed.

## 14. Risks / review points

- Provision the durable local directory/mount for UID/GID 10001 and confirm all
  notification jobs use the same file. Absolute-path validation cannot itself
  prove a mount is persistent. No network filesystem or independent replica files.
- Five-minute monitoring plus existing hourly surveillance and 30-minute
  freshness WARNING can cause routine warning/recovery cycles; thresholds were
  deliberately preserved.
- Telegram acceptance followed by a timeout/crash before state commit can cause
  a later duplicate. `sendMessage` has no idempotency key; this is not exactly-once
  delivery. No full incident queue is implemented.
- Snapshot coverage and 24-hour metrics use different existing time windows.
  Last scheduled start is not available; latest completion is shown instead.
- No live Telegram or PostgreSQL integration smoke was performed. Two DB tests
  were skipped because the dedicated test database was not configured.
- Independent review findings were resolved: coverage labeling, recurrence after
  failed recovery, WARNING daily coverage, and absolute state paths.
