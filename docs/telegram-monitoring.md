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
24-hour summary. A report at 08:00 ICT is not a report of yesterday's calendar
day. It does not label completed health-record count as scheduled-run coverage.

`latest_run` is the latest completed health record, not the latest scheduled
start. Messages label it as a completion. Scheduled-start time is unavailable in
`HealthSummary` and is omitted. No extra analytics query is added. Unknown
values remain N/A; zero relevant signals remain valid.

Recent failures are bounded, sanitized metadata, without raw exceptions,
provider responses, prompts, article bodies, or sensitive URL query strings.
Plain text uses no Telegram parse mode and disables link previews.

## Proposed scheduling (review before applying)

There is an existing monitoring command, but no periodic monitoring job is
defined in the checked-in deployment configuration. Add `--notify` to the
operator's existing monitoring-only job if one is already installed. Otherwise,
the proposed independent monitoring cadence is every five minutes. This sends
on the first observing evaluation, with up to five minutes of detection latency.
Keep it separate from the surveillance job and its success/exit handling.

Daily time: **08:00 Asia/Bangkok = 01:00 UTC**, throughout the year. For a host
whose cron is explicitly configured in UTC, proposed entries are:

```cron
# Replace episignal-api with the actual existing API container name.
0 1 * * * docker exec episignal-api python -m episignal_backend.monitoring_runner --daily-report
*/5 * * * * docker exec episignal-api python -m episignal_backend.monitoring_runner --notify
```

Do not assume server timezone. On a cron implementation supporting `CRON_TZ`,
an alternative is `CRON_TZ=Asia/Bangkok` with `0 8 * * *` for the daily command.
Do not install both alternatives. Review the actual runtime/container name and
log capture in the operator's scheduler. This change does not install or edit
cron, Coolify settings, VPS files, or production containers.

**Cadence review:** the existing hourly surveillance cadence and freshness
WARNING at 30 minutes can produce routine WARNING/recovery cycles when observing
every five minutes. Duplicate suppression removes unchanged incidents, not real
status changes. Thresholds remain unchanged; review this expected behavior before
enabling the proposed schedule.

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
supersedes that pending recovery. No numeric values enter the fingerprint. SQLite transactions
serialize comparison, send, and checkpoint; another writer waits at most one
second before failing safely. A corrupt/unwritable/locked file prevents sending
and emits a sanitized `notification_failed` log; do not silently reset it.

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
