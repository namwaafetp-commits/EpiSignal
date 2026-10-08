# Handoff — production dashboard availability

Date: 2026-10-08. State: building. Baseline: `cb616c5` on
`codex/next-iteration`.

The user authorized fixing production availability after SSH diagnostics and a
Supabase disk I/O warning. This supersedes the old UI-only restriction on
production access; the previous handoff is archived at
`docs/handoffs/2026-10-08-before-production-reliability.md`. Preserve the user's
uncommitted footer, CSS, image, and critique changes.

## Bounded implementation

1. Cache successful public dashboard reads within each API process for 60
   seconds. Preserve response shape, filters, ranking mode, and stored evidence
   timestamps. Bound the cache to 32 entries and coalesce concurrent misses.
2. Add web `GET /health/live` with no API or database dependency. Point the
   Docker health check at it with a bounded network timeout.
3. Enable Docker init for both EpiSignal services to reap orphaned child
   processes. Allow the frontend 15 seconds for cold dashboard refreshes;
   observed direct API requests exceeded the old five-second timeout.
4. Run focused regressions, independent review, and the full repository gate.
   Record actual outcomes; do not mark the roadmap verified without a passing
   `corepack pnpm verify` run.
5. Deploy only the reviewed commit through the existing Coolify application.
   Preserve old images and a protected copy of the current compose definition.
   Verify both health checks, dashboard contents, repeated request latency,
   public web rendering, and continued scheduler container discovery.

The user explicitly approved testing through the existing public dashboard API
and the dedicated public web liveness endpoint. Test database/time boundaries
without touching production data. No schema migration or model change is part
of this fix.

## Remaining external constraints

- OpenRouter's account credits were exhausted, then funding was restored. A
  read-only check found $19.8243 remaining, and scheduled processing produced a
  stored summary on October 8 at 10:28 Bangkok. Do not change models, buy credits,
  or trigger a paid backfill.
- The two-vCPU VPS showed substantial CPU steal. Application changes cannot
  guarantee recovery of provider CPU capacity.
- Supabase's warning reports a depleting I/O budget, not confirmed present
  exhaustion. Historical statistics are not current utilization measurements.
- Netdata was stopped with user authorization during diagnosis. Leave it
  stopped pending a separate decision.

## Rollback

Keep the previous image tags and compose definition before deployment. If the
new services fail acceptance, restore the prior compose definition and recreate
only EpiSignal API/web from the retained images. No data restore or migration
rollback is needed. Existing cron wrappers discover the running API container
by application label and must continue doing so.
