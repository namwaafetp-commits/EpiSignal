# Event summary quality and spend

## Production baseline

On November 3, production was running `72cda55` with Alembic revision
`20260917_0026`. The monitoring window showed 24 completed scheduled runs,
zero fatal errors, and 37 accepted summaries out of 99 attempts. The one-day
AI ledger reported $0.019903 in summary spend, including $0.011825 for 61
rejected responses. Cost per accepted summary was $0.000538, including rejected
and unavailable attempts. Production logged generic shape failures, which did
not identify the violated validation rule.

## Implementation

Commit `31125f9` removes previous generated narrative from requests while
retaining linked articles and observations. It states the exact word limit and
records validator error codes without response content. Scheduled and manual
summarization share the pipeline lock. A rejected request's fingerprint and
timestamp commit with its cost record. An identical request is deferred for six
hours. Changes to the evidence, prompt, or model bypass that cooldown.

## Rollout and measurement

`corepack pnpm verify` exited 0. Web tests reported 190 passed across 24 files.
Python reported `1583 passed, 2 skipped, 2 warnings in 61.42s`. Format, lint,
type checks, generated contracts, and the Next.js production build passed.
`corepack pnpm test:pipeline` reported `18 passed in 0.84s`.

The additive revision committed before the push. The old dashboard API
returned HTTP 200 after migration. The prior compose and environment were
backed up under `/data/coolify/backups/episignal-summary-20261103` with
restricted permissions. Coolify deployment `1b23f47387a5e683a01b543c`
finished. Both replacement images run `31125f9` and report healthy.
Alembic reported `20261103_0027 (head)`. API and web liveness, dashboard, and
homepage all returned HTTP 200. A read-only smoke check built requests and
fingerprints for three production candidates with zero provider calls.

The migration used a three-second PostgreSQL lock timeout. Roll back by
restoring the retained `72cda55` images and saved compose/environment with the
nullable columns in place.

After the first complete 24-hour production window, compare accepted summaries,
paid attempts, cooldown deferrals, validator codes, and cost per accepted
summary. Report accepted summaries per eligible event alongside acceptance per
attempt so suppression does not look like improved response quality.
