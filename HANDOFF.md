# Handoff — UI v2 editorial redesign

Date: 2026-09-13. State: building.

Implement the user-supplied [design](docs/superpowers/specs/2026-09-13-ui-v2-design.md) following the [plan](docs/superpowers/plans/2026-09-13-ui-v2.md). This request supersedes the previous active handoff, archived in docs/handoffs/2026-09-13-before-ui-v2.md.

Preserve all backend/API/data behavior. Work on codex/next-iteration, commit and push only after review and verification. Never access production, VPS, or Coolify; never deploy. Use local fixtures for visual QA.

Public testing seams approved in the user specification: theme selection/storage; Map/Briefing navigation; URL filters/history; map drawer and reading pane; full event rendering including bullets, legacy summaries and source links; responsive keyboard interaction. Parent owns shell/feed/theme and integration; a bounded independent worker may own event content/detail. Final reviewers independently assess standards and specification against 198964ab5041666ac0490e09c4fe02904aeb348f.
