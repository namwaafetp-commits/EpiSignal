# Privacy-preserving Umami analytics report

Date: 2026-09-13
Scope: repository/code only. No VPS, Coolify, production service, production
environment, production database, or deployment was accessed.

## ANALYTICS

Provider: Separately self-hosted Umami
Integration: Optional root-layout `next/script` plus a typed `trackEvent` abstraction and sanitized manual page-view tracker.
Disabled behavior: If either public Umami variable is missing, the script is omitted and all tracking calls are no-ops.

## EVENTS

view_switch: Map or Briefing navigation
theme_change: Light, Dark, or System selection
filter_change: Period, disease group, host, country, or status allowlist
search_used: Result-count bucket only
map_event_open: Controlled disease group and host sector
briefing_event_open: Controlled disease group, host sector, and source-count bucket
reading_pane_open: Empty payload
full_event_open: Empty payload
source_click: Bounded normalized source domain

## PRIVACY

Search text sent: No
Headline sent: No
Summary sent: No
Event ID sent: No; event page paths are normalized to `/events/:public_id`
Full source URL sent: No
Identifiers sent: No

Automatic page views are disabled. Manual page views use only `/`, `/briefing`,
and `/events/:public_id`, with generic titles and no referrer payload.
Production setup requires Umami 3.2.0 or newer for `data-auto-pageview`.

## CONFIG

NEXT_PUBLIC_UMAMI_WEBSITE_ID: Added to web local and production examples; no real value committed
NEXT_PUBLIC_UMAMI_SCRIPT_URL: Added to web local and production examples; no real value committed

## TESTS

Analytics: 10 focused analytics/page-view tests; full web suite 157 passed across 20 files
Privacy: Explicit sanitized event-detail path, missing-config, normalized-domain, and prohibited-content regression coverage
Web: 157 passed
Python: 1,533 passed, 2 skipped, 2 existing warnings

## VERIFY

pnpm verify: PASS
Typecheck: Web TypeScript passed; mypy passed for 149 source files
Lint: ESLint and Ruff passed
Build: Next production build passed; routes generated successfully
Contracts: Regenerated and unchanged
Alembic: `20260912_0025` (head)

## DOCS

Umami operations guide: [docs/operations/umami.md](../operations/umami.md)

## REVIEW

Standards/spec review completed. The Server Component boundary, sanitized Umami
payloads, minimum supported Umami version, and half-configured disable behavior
were corrected before the final verification gate.

## GIT

Previous HEAD: `0b532cb`
New HEAD: this report is included in the completion commit
Remote HEAD: `0b532cb` before push
Tracked tree: Analytics implementation, tests, examples, operations guide, and this report; unrelated pre-existing untracked files preserved

## PRODUCTION

Deployed: NO
VPS accessed: NO
Coolify accessed: NO
Production env changed: NO
main merged: NO
