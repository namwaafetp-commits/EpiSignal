# Production dashboard availability — 2026-10-08

## Scope and evidence

The user authorized production diagnosis and reliability fixes for EpiSignal.
The implementation baseline was `cb616c5`; the reviewed runtime implementation
is `72cda5533acf0ffba1b80bc67d785c3b3f031a16`. The subsequent test-only commit
`1a495906db32fcc0833d79a1e6ae7ff8aa8547ae` bounds web test workers to two.

The public web service became unavailable when Docker marked its homepage-based
health check unhealthy. Rendering that page called the API readiness endpoint
and loaded the complete event dashboard. Direct dashboard requests were observed
at approximately 7.6 seconds, beyond the frontend's five-second deadline. The
web container also accumulated approximately 5,000 orphaned health-check child
processes without an init process.

Separate constraints were observed: substantial VPS CPU steal, a Supabase disk
I/O budget warning, and an exhausted OpenRouter account. Read-only database
statistics showed a 99.99% historical cache hit rate. A final lightweight
15-second sample had no new block reads or temporary-file writes; this does not
establish present budget availability or identify the warning's cause. Reading
query statistics with query text itself spilled to temporary files, so those
heavier diagnostic probes were stopped.

OpenRouter funding was subsequently restored: a read-only credit check returned
$30 total credits, $10.1757 usage, and $19.8243 remaining. Existing scheduled
processing produced a stored summary at `2026-10-08T03:28:33.822049Z` (10:28
Bangkok), and the summarized-event count increased from 1,135 to 1,136. No
manual model request, credit purchase, model switch, or paid backfill was used.

## Implementation

- Cache successful dashboard reads for 60 seconds per API process, with a
  32-entry least-recently-used bound. Filters and ranking mode have distinct
  entries. Stored evidence timestamps and response contracts are preserved.
- Coalesce same-key successes and failures through a shared Future. Database
  I/O runs outside the cache-map lock; waiters suspend asynchronously. Failure
  is shared with current waiters and does not prevent a later retry.
- Add web `GET /health/live`, independent of the backend and database. Docker
  probes it with a two-second network deadline instead of rendering the homepage.
- Enable Docker init for API and web services to reap orphaned child processes.
  Keep API liveness asynchronous and independent of synchronous worker capacity.
- Allow 15 seconds for cold dashboard refreshes. Cached responses retain the
  60-second freshness bound; failures are not retained beyond that bound.
- Limit the web test runner's TypeScript configuration search to the web app
  and use at most two thread workers after Windows fork-worker startup timeouts
  and memory contention under unrestricted parallel execution.

The user's existing footer, CSS, images, critique files, and footer test were
preserved and excluded from implementation commits and deployment. No database
migration, schema change, data deletion, or unrelated service change is included.

## Review

### Standards

The initial independent review identified a global lock around database I/O
that could block unrelated cached requests. The correction uses per-key shared
Futures and asynchronous waiters, with regression coverage for hot-cache
availability, liveness, concurrent failure/recovery, and capacity eviction.
Focused re-review of `cb616c5...72cda55` found no unresolved actionable findings.

### Specification

The initial independent review identified repeated database attempts after
concurrent failures. Six simultaneous public API requests now share one failed
database attempt, and a later request can recover. Focused re-review found no
missing requirements, incorrect behavior, or scope creep.

Both review findings were corrected; final findings: Standards 0, Specification 0.

## Verification

The cache outage regression first failed with HTTP 500 instead of the expected
cached HTTP 200. The concurrent-failure regression first observed six database
attempts instead of one. Both passed after their respective corrections.

Focused verification:

```text
uv run pytest apps/api/tests/test_dashboard_cache.py -q
6 passed

uv run pytest apps/api/tests packages/backend/tests/test_event_read.py -q
90 tests passed before the three additional concurrency/capacity regressions

Dedicated web liveness regression: 1 passed
uv run mypy apps/api/src packages/backend/src
Success: no issues found in 157 source files
```

`corepack pnpm verify` completed with exit code 0. Review corrections were
applied while the gate was running; the corrected cache additionally passed its
focused regression suite and a subsequent complete Python typecheck. The final
gate output was:

```text
334 files already formatted
All matched files use Prettier code style!
All checks passed!
Success: no issues found in 157 source files
Test Files  24 passed (24)
Tests  190 passed (190)
1580 passed, 2 skipped, 2 warnings in 181.06s (0:03:01)
openapi.json -> src/index.d.ts
Compiled successfully in 3.8min
Finished TypeScript
Generating static pages using 11 workers (10/10)
```

Contracts regeneration produced no semantic diff. The build included the dynamic
`/health/live` route. Existing Vite configuration, jsdom navigation, and Python
deprecation warnings were emitted. The local gate includes the user's existing
UI changes, which are not deployed.

An independent repeat at fixed commit `72cda55` failed with exit code 1: format,
lint, and types passed; web tests had 186 passes and four five-second UI test
timeouts. Python tests, contracts, and build did not run in that attempt. The
machine had approximately 1.3 GB free memory. A subsequent unchanged-suite run
with `vitest run --maxWorkers=2` passed all 190 tests in 62.20 seconds without
increasing timeouts. Commit `1a49590` makes that worker bound explicit. The
test-only commit uses `[skip cd]` and does not alter the runtime deployment.

The independent full gate at unchanged commit
`1a495906db32fcc0833d79a1e6ae7ff8aa8547ae` then passed with exit code 0:

```text
334 files already formatted
All matched files use Prettier code style!
All checks passed!
Success: no issues found in 157 source files
Test Files  24 passed (24)
Tests  190 passed (190)
1580 passed, 2 skipped, 2 warnings in 228.68s (0:03:48)
contracts generation and git diff --exit-code: passed
Compiled successfully in 83s
Finished TypeScript in 15.4s
Generating static pages using 11 workers (10/10) in 4.0s
[verify-exit-code] 0
```

Both independent source reviews are clear. The subsequent worker-cap change
also received an independent standards review with no actionable findings.

## Deployment and rollback

The reviewed commit was pushed and queued through Coolify as deployment
`c3eec9583ca26efea1f7438a`; it finished at `2026-10-08T04:46:13Z` (11:46
Bangkok). A protected
rollback directory was created on the VPS at
`/root/episignal-rollback-20261008`, containing the previous compose definition,
environment file, and API/web image identities. Existing images are retained.
Rollback restores the prior compose and environment and recreates only
EpiSignal services from retained images; no database rollback is needed.

The VPS continued to show 80% CPU steal during the build. Web compilation took
8.3 minutes and TypeScript took 4.3 minutes; Python dependency bytecode setup
took approximately 24 minutes. Once the reviewed web image was available, web
was restored first with a protected compose override changing only its image
and `init: true`. The existing API contract remains compatible. The normal
Coolify deployment subsequently finished the API image and replaced both services.

Staged web acceptance:

```text
web runtime image: 72cda55
web Docker health: healthy; init: true; zombie processes: 0
API /health/live: HTTP 200
web /health/live: HTTP 200
dashboard: HTTP 200; 1,138 items
newest report: 2026-10-08T04:20:42.412240Z
newest summary: 2026-10-08T04:20:42.615086Z
homepage: HTTP 200, 8.608 s, 4 event links, no unavailable message
briefing: HTTP 200, 11.687 s, 99 event links, no unavailable message
desktop HTTPS homepage: HTTP 200, 10.514 s, no unavailable message
```

These initial dashboard timings still use the old uncached API. Scheduled
processing has continued without a manual model call or backfill. The cron
wrappers discover the API dynamically using the `name=episignal-api` filter.
Browser automation returned `net::ERR_BLOCKED_BY_CLIENT`; visual QA is
unavailable, and terminal HTTPS/HTML checks do not claim visual verification.

Final runtime acceptance used both images at `72cda55`:

```text
API and web Docker health: healthy
API and web init: true
API and web zombie processes: 0
API /health/live: HTTP 200, 0.610 s
web /health/live: HTTP 200, 0.296 s
API loopback /health/ready: HTTP 200, 2.390 s
API loopback dashboard cold read: HTTP 200, 8.210 s
API loopback dashboard cached read: HTTP 200, 0.694 s
public dashboard repeated reads: HTTP 200, 2.398 s then 1.096 s
public dashboard payload: 1,141 items, identical SHA-256 on repeated reads
newest report: 2026-10-08T06:12:14.415550Z
newest summary: 2026-10-08T06:12:14.616193Z (13:12 Bangkok)
public homepage from VPS: HTTP 200, 6.395 s
public briefing from VPS: HTTP 200, 12.710 s, 101 event links
final desktop homepage: HTTP 200, 11.693 s, no unavailable message
final desktop briefing: HTTP 200, 8.315 s, no unavailable message
cron selector matches: episignal-api-u7d7nvflnxupayccxg2qlalv-035154223772
Netdata: exited
```

Initial final-runtime acceptance had two 30-second public dashboard timeouts
and unavailable HTML; later checks also observed a homepage timeout before
successful repeated public checks. These failures are retained as evidence,
not represented as a clean uninterrupted acceptance window. Read-only database
diagnostics connected in 1.396 seconds, and an API thread-stack snapshot showed
two idle workers. Direct API reads and later public reads succeeded without a
restart or configuration change. Worker exhaustion and a proxy configuration
fault were not established; no speculative change was applied for either.

The bounded application acceptance conditions passed after recovery. This is
not a load-test result or a guarantee of stable provider capacity. A fresh VPS
sample still showed 81% CPU steal and a large runnable queue. Coolify and Honcho
were the largest consumers in a container sample; no limits or restarts were
applied to those separate applications. Substantial variable latency and
transient timeouts remain an operational risk under host CPU contention.

Netdata remains stopped as previously authorized. VPS provider capacity and
Supabase's actual I/O budget remain external operational constraints; this patch
reduces application work but does not claim to resolve provider throttling.
