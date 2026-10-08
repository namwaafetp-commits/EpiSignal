# GDELT discovery reliability hotfix

**Date:** 2026-09-10  
**Branch:** `codex/next-iteration`  
**Previous HEAD:** `7a4d28745a61b26ec44afac7098b9497e2643209`

## Root cause

Local inspection confirmed all four reported causes:

- `gdelt_request_delay_seconds` existed in settings but was not passed to the
  production GDELT client constructors.
- HTTP 429 responses were eligible for the normal three-attempt retry loop.
- Active rules were consumed in repository order, so early rules could
  repeatedly reach the circuit before later rules.
- The discovery stage returned counts only, so a run with all attempted rules
  failed could still be recorded as successful by the chain runner.

## Request behavior

### Old

- `GdeltDocClient()` used no configured request pacing.
- Each failure, including HTTP 429, could use up to three attempts with the
  existing backoff.
- The circuit opened only after the consecutive-failure or elapsed-time
  protections fired.
- Active rules always started at the repository's first rule.

### New

- `GdeltDocClient(request_delay_seconds=...)` enforces the configured minimum
  interval between request starts using injected monotonic time and sleep.
  Slow requests consume the interval; they do not add an unnecessary full
  delay afterward.
- HTTP 429 stops the current rule immediately and opens the in-memory circuit
  with `circuit_open_reason=rate_limited`.
- Timeout, transport, and transient 5xx retry behavior remains bounded and
  unchanged.
- Active rules rotate deterministically by the UTC run hour, without a
  persistent cursor or database change.
- The configured delay is wired into scheduled discovery, standalone discovery,
  scheduled retrieval construction, and standalone retrieval construction.

## Review corrections

- An HTTP 429 returned by the HTTP fallback after an HTTPS transport failure
  now terminates `_request()` immediately. The rule makes exactly two requests
  in that path (`https`, then `http`), and no retry follows the confirmed 429.
- `begin_run()` now clears `_next_request_at`, so a reused client can start the
  next run immediately while preserving pacing between requests within that
  run.
- Regression tests cover fallback-429 termination, rate-limit circuit state,
  and per-run pacing reset.

## Health behavior

- Provider succeeded with zero articles: `rules_attempted > 0`,
  `rules_succeeded > 0`, `discovered=0`; discovery remains healthy.
- Provider unavailable: `rules_attempted > 0`, `rules_succeeded=0`, and every
  attempted rule failed; discovery reports `ok=false` with
  `DiscoveryUnavailable`, while later chain stages still execute.
- Partial failure remains usable when at least one rule succeeds.

## Safe diagnostics

An unexpected HTTP 200 payload logs metadata only, for example:

```text
gdelt_invalid_schema status_code=200 content_type=application/json payload_type=dict keys=message,status articles_type=NoneType
```

No response body, article content, URL, query text, or secret is logged.
The existing plain-text `No results...` handling remains unchanged.

## Tests and verification

Focused coverage includes pacing, slow-request elapsed-time behavior, 429
retry suppression and per-run reset, timeout/5xx retries, circuit counters,
fair rule rotation, discovery health semantics, safe schema diagnostics, and
scheduled/standalone delay wiring.

Successful verification command:

```text
UV_NO_SYNC=1 corepack pnpm verify
```

Results:

- Format: 309 files formatted; Prettier passed.
- Lint: web ESLint and Python Ruff passed.
- Typecheck: web TypeScript and mypy passed; 147 Python source files checked.
- Web tests: 125 passed across 15 files.
- Python tests: 1,471 passed, 2 skipped, 2 existing deprecation warnings.
- Contracts: generated contracts matched the working tree.
- Build: Next production build passed.
- Alembic head: `20260908_0023`.

## Invariants

No DeepSeek, Gemini, or Mistral behavior changed. Event matching, disease
taxonomy, host-sector classification, summary format, cron configuration,
production environment, requeue behavior, and historical backfill were not
changed. No database migration was added; Alembic head remains
`20260908_0023`.

## Deployment and Git

- New commit: recorded in the final handoff for this report.
- Remote HEAD: `7a4d28745a61b26ec44afac7098b9497e2643209`.
- Working tree: clean after commit.
- Push status: not pushed; local branch is one commit ahead of remote.
- Deployment: **not deployed**.
- VPS: **not accessed**.
- Coolify: **not accessed**.
- Production database: **not modified**.
