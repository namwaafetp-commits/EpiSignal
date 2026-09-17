# Telegram monitoring (deployment proposal; not deployed)

The existing `episignal_backend.monitoring_runner` evaluates production health
with `summarize_health()` and returns `HealthSummary`. Telegram only formats that
summary, compares notification state, and sends text. It makes no AI requests,
diagnoses, remediation, pipeline executions, requeues, backfills, or event writes.

## Configuration

Use the existing `EPISIGNAL_` settings convention:

| Variable | Purpose |
| --- | --- |
| `EPISIGNAL_TELEGRAM_BOT_TOKEN` | Bot credential; a masked `SecretStr` |
| `EPISIGNAL_TELEGRAM_CHAT_ID` | Target chat identifier; also masked |
| `EPISIGNAL_TELEGRAM_STATE_PATH` | Absolute path to SQLite file on a persistent local filesystem |

Create a bot using Telegram's BotFather, add it to the intended group/channel or
start a direct chat, and grant permission to send there. Obtain that chat's ID
from a bot update using Telegram's official tools/API in a private operator
session. Do not paste tokens or credential-bearing API URLs into logs, tickets,
browser histories, or shell history. See the official
[Bot API documentation](https://core.telegram.org/bots/api#sendmessage).

Omitting/blanking the token or chat ID disables all sends, with the explicit
`telegram_notifications_disabled` log. Daily/alert modes also require a state
path; they never silently fall back to an ephemeral file. Existing database
settings still apply to monitoring. The smoke command loads settings but opens
no database connection.

## Commands

Run inside the existing API image or an installed repository environment:

```sh
# Original read-only structured monitoring output, no notifications/state writes:
python -m episignal_backend.monitoring_runner

# Evaluate once, emit the same JSON, then send only meaningful transitions:
python -m episignal_backend.monitoring_runner --notify

# Evaluate once and send the daily report once per Asia/Bangkok calendar date:
python -m episignal_backend.monitoring_runner --daily-report

# Static notification only; no monitoring queries or notification-state writes:
python -m episignal_backend.monitoring_runner --telegram-smoke-test
```

From a development checkout prefix with `uv run --package episignal-backend`.
Modes are mutually exclusive. A safe manual smoke test uses the last command
with a configured test bot/chat; it never invokes the surveillance pipeline.
All automated tests mock Telegram. No live smoke send was performed during
implementation.

## Report windows and meaning

Coverage is the evaluator's **current Bangkok calendar day** scheduled-slot
coverage, including its active-run grace and activation rules. Completed runs,
success, runtime, fatal errors, stages, and throughput use the existing trailing
24-hour summary. A report at 08:20 ICT is not a report of yesterday's calendar
day. It does not label completed health-record count as scheduled-run coverage.

`latest_run` is the latest completed health record, not the latest scheduled
start. Messages label it as a completion. Scheduled-start time is unavailable in
`HealthSummary` and is omitted. No extra analytics query is added. Unknown
values remain N/A; zero relevant signals remain valid.

Recent failures are bounded, sanitized metadata, without raw exceptions,
provider responses, prompts, article bodies, or sensitive URL query strings.
Plain text uses no Telegram parse mode and disables link previews.

## Proposed scheduling — PROPOSED — NOT INSTALLED

**IMPLEMENTED IN CODE:** the existing monitoring-only command, evaluator,
notification state machine, and one-second SQLite lock timeout are unchanged.
Local synthetic timing and lock-contention regression tests exercise those real
interfaces. No production scheduler hook or cron job has been installed.

**PROPOSED FOR PRODUCTION DEPLOYMENT:** notify immediately after the existing
scheduled wrapper finishes (including failure/timeout), plus independent watchdog
checks at minutes **16 and 26** each hour. Send the daily report at **08:20 ICT
(01:20 UTC)**, with one later eligible attempt at **08:21 ICT (01:21 UTC)**.
The existing daily checkpoint suppresses the second attempt after success.

### Repository evidence and explicit assumptions

The task supplies hourly surveillance as a known fact. Repository
`operational_monitoring.py` has a 60-minute schedule interval, an active-run grace
of one hour, and a comment relating that grace to a 3600-second wrapper timeout.
`pipeline_runner.py` records completion and best-effort health telemetry before
returning; its PostgreSQL advisory lock and exit behavior stay unchanged.
`scripts/run-pipeline.ps1` forwards `--trigger scheduled` and preserves failures.
The older Windows scheduling document is not evidence of current VPS cron.
The current Linux production wrapper is not checked in and was not inspected.

**TO VERIFY DURING DEPLOYMENT:** the proposal assumes scheduled starts at minute
00 and ordinary completion before minute 15. The synthetic representative run
is six minutes, not a measured production runtime. Tests also cover 0.1-minute
and 14.9-minute runs. Verify actual phase, start jitter, runtime, wrapper failure
handling, and timeout locally on the VPS during the separate deployment task.
If the hour starts at a different phase, shift the proposed checks consistently;
do not install these clock times unchanged without that check.

### Why this stays quiet for normal hourly runs

For starts at :00 and completion in under 15 minutes, post-run freshness is zero.
At :16 and :26, a normally completed run is always less than 30 minutes old. The
checks therefore avoid the normal 30–60-minute freshness WARNING interval without
altering or masking any evaluator result. They still send any stage/run/coverage
WARNING or CRITICAL present in the same snapshot. Daily reporting reads the normal
snapshot after the morning run and does not update abnormal incident state.

Six-minute synthetic example (ICT):

| Invocation | Latest completion | Freshness | Existing evaluator |
| --- | --- | --- | --- |
| 08:10, old polling | 08:06 | 4m | HEALTHY |
| 08:35, old polling | 08:06 | 29m | HEALTHY |
| 08:40, old polling | 08:06 | 34m | WARNING |
| 09:05, old polling | 08:06 | 59m | WARNING |
| 09:10, old polling | 09:06 | 4m | HEALTHY / recovery |
| 08:06, proposed post-run | 08:06 | 0m | HEALTHY |
| 08:16, proposed watchdog | 08:06 | 10m | HEALTHY |
| 08:26, proposed watchdog | 08:06 | 20m | HEALTHY |
| 09:06, proposed post-run | 09:06 | 0m | HEALTHY |

The old five-minute proposal repeatedly generated WARNING/recovery pairs during
normal operation. It is superseded; do not keep that polling job alongside this
proposal. The raw monitoring command still reports freshness WARNING between
runs when asked at that time; health semantics have not changed.

### Independent watchdog and missed/late runs

Watchdog jobs must run independently of the surveillance wrapper, so a missing,
killed, or stuck wrapper cannot prevent the checks. With the 08:00 run missing
and previous completion at 07:06, the 08:16 check sees **70-minute freshness**, so
it is CRITICAL under the existing >60-minute rule. Missing scheduled coverage
can also be abnormal. An active run still unfinished at 08:16 has the same stale
completion evidence even while its coverage receives the existing active-run
grace. The 08:26 check retries failed delivery or suppresses an unchanged incident.

A stage failure alerts as soon as the proposed post-run hook observes its
persisted telemetry; the watchdog is the fallback if that hook does not run.
A late completion triggers post-run evaluation. Recovery is sent only when the
**overall existing result** returns HEALTHY. A missing scheduled slot can keep
coverage abnormal until the Bangkok calendar day changes, even after freshness
recovers. Runtime/stage problems may persist in the trailing 24-hour aggregate.
Do not force a recovery merely because a later run completed.

### Exact proposed UTC cron entries

**PROPOSED — NOT INSTALLED. TO VERIFY DURING DEPLOYMENT:** `episignal-api` below
is an example container name, not a verified production name. Server cron must
be explicitly UTC for these expressions. Keep the existing hourly surveillance
entry unchanged; add the post-run completion hook separately during deployment.

```cron
# PROPOSED — NOT INSTALLED. Watchdog checks, every hour (UTC and ICT minute 16/26).
16,26 * * * * docker exec episignal-api timeout 45s python -m episignal_backend.monitoring_runner --notify
# PROPOSED — NOT INSTALLED. 08:20 ICT primary; 08:21 ICT bounded retry (01:20/01:21 UTC).
20,21 1 * * * docker exec episignal-api timeout 45s python -m episignal_backend.monitoring_runner --daily-report
```

The primary daily time is four minutes after :16 and six minutes before :26;
the retry is at :21. No periodic notification modes intentionally start together.
For an explicitly Asia/Bangkok cron, the daily hour is 8 instead of 1; use only
one timezone convention. Confirm the image contains `timeout`; bound monitoring
inside the container so termination releases the SQLite lock. No surveillance
command is wrapped in this new monitoring timeout.

### Proposed post-run completion hook (documentation only)

**TO VERIFY DURING DEPLOYMENT:** adapt the actual wrapper's existing completion
handler, after its pipeline command and health persistence finish. Save the exact
original exit code as `pipeline_status` before any notification command. Both
success and failure/timeout paths must reach the hook; a wrapper using `set -e`
needs its existing error handler, not an unprotected append to the success path.
The original pipeline invocation, arguments, lock, and timeout remain unchanged.
Use the actual API container in `EPISIGNAL_API_CONTAINER`.

```sh
# PROPOSED — NOT INSTALLED. Inside the existing completion handler:
# pipeline_status already contains the original scheduled command's exit status.
if timeout 60s docker exec "$EPISIGNAL_API_CONTAINER" timeout 45s \
    python -m episignal_backend.monitoring_runner --notify; then
    :
else
    printf '%s\n' 'post_run_notification_failed' >&2
fi
exit "$pipeline_status"
```

The hook executes monitoring only and its result never replaces the saved
surveillance exit status. A hard-killed wrapper may never reach it; independent
watchdogs cover that case. This snippet is a proposal, not a claim that actual
wrapper integration or timeout behavior has been verified.

### TO VERIFY ON VPS DURING DEPLOYMENT

None of the following were verified in this local-only task:

- Actual production cron, hourly phase, runtime envelope, and wrapper completion/error paths.
- Actual API container name and availability of the proposed timeout commands.
- Server timezone / cron timezone convention.
- Writable persistent notification directory and UID/GID ownership.
- Coolify environment variables for bot, chat, and absolute state path.
- Notification state mount survives container replacement; every job uses the same file.
- No duplicate scheduler entries, including removal of the superseded polling proposal.
- Post-run notification failure leaves the original surveillance exit status unchanged.

## Durable state and deployment preparation

The repository has no generic durable monitoring configuration/incident store.
Domain tables and pipeline telemetry are not notification checkpoints. A small
stdlib SQLite file avoids any PostgreSQL schema/Alembic migration and keeps
surveillance queries read-only. The current Alembic head is unchanged.

For example, prepare a host directory `/var/lib/episignal-notifications` owned by
the API container user **UID/GID 10001**, writable only by that user. After review,
mount it into the container at `/var/lib/episignal-notifications` and set
`EPISIGNAL_TELEGRAM_STATE_PATH=/var/lib/episignal-notifications/state.sqlite3`.
The directory must already exist. The optional
[`docker-compose.monitoring.example.yaml`](../docker-compose.monitoring.example.yaml)
shows the environment and mount additions; it is not used by default.

Every notification invocation for a destination must use the same file on the
same host/local filesystem. Do not use NFS or independent replica volumes.
Preserve the directory across container replacements and restarts; do not
delete it during deployment. It stores no token, chat ID, message body, or
failure details. A hash of bot credential/chat separates destinations. Credential
rotation or destination changes create a fresh checkpoint and may alert again.

SQLite's `notification_state` table contains a per-channel key, delivery
checkpoint, latest observed timestamp, observed status/fingerprint, and pending
recovery's previous severity. Alerts store severity and the stable fingerprint
of abnormal metric identities/statuses; daily reports store the Bangkok date.
Each meaningful observation invalidates the old delivery acknowledgement, so a
failed recovery cannot suppress a later recurrence of the same incident. Failed
recoveries remain pending while health stays GREEN; a new abnormal condition
supersedes that pending recovery. No numeric values enter the fingerprint.

SQLite still serializes comparison, send, and checkpoint with `BEGIN IMMEDIATE`
and the existing one-second wait. There is no persistence or locking code change.
Removing intentional simultaneous starts resolves the documented collision; the
one-second timeout remains an explicitly best-effort boundary, not a guarantee
against every overlap. A late post-run hook or manual invocation can still
contend with another job. The losing invocation sends nothing, does not advance
its observation/delivery checkpoint, logs `notification_failed`, and remains
eligible later. Local regression tests cover both a blocked daily attempt and a
blocked alert attempt, followed by successful retry and duplicate suppression.
The :21 daily retry and :26 watchdog provide separate later eligible attempts.
If both daily attempts fail, retry the same daily command manually after checking
the separate delivery logs; do not reset the state. A corrupt/unwritable file also
fails closed. The mount and all SQLite side files must remain on durable local
storage; no sidecar database, migration, lock queue, or new service was added.

GREEN stays quiet. A first WARNING/CRITICAL alerts. Severity changes and different
abnormal metric sets alert, including escalation and partial improvement.
Unchanged abnormal fingerprints stay quiet. WARNING/CRITICAL to HEALTHY sends
one recovery and clears the abnormal checkpoint; NEUTRAL does not claim recovery.
Older observations cannot overwrite newer state. Daily sends do not reset
incident state; repeat daily invocations on the same Bangkok date are suppressed.

Delivery has a 10-second socket timeout, no redirects and no immediate retries.
HTTP/API/network failures log fixed event names without response bodies or URLs.
The current observation is marked delivered only after acknowledgement. Failed sends
remain eligible on the next observing invocation. An incident that begins and
ends entirely during a Telegram outage may never be delivered; there is no queue.
A timeout after server acceptance, or process termination between acceptance
and SQLite commit, may duplicate a message later. Telegram `sendMessage` provides
no idempotency key, so exactly-once external delivery cannot be guaranteed.

Monitoring evaluation failure sends no report/recovery and leaves notification
state untouched; it exits 1 with `monitoring_evaluation_failed`. `--notify`
preserves the successful monitoring exit code even if delivery fails; its JSON
health result is unchanged. Daily/smoke delivery failures exit 1. Disabled
configuration exits cleanly (0) with an explicit log, not a success claim.
Telegram failure cannot make the surveillance pipeline fail: notifications are
only invoked by the separate monitoring command.

Rollback/disable: remove notification cron invocations or blank bot/chat settings.
The original no-flag monitoring command remains available. Preserve state for a
later re-enable. Do not modify or roll back surveillance data.
