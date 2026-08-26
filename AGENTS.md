# EpiSignal Agent Instructions

These instructions apply to every coding agent working in this repository.

## Project skills

Project-local skills live in `.agents/skills/`. Agents with skill discovery must load every applicable skill before acting. Agents without skill discovery must read the relevant `.agents/skills/<skill>/SKILL.md` files directly and follow them as process instructions.

- Use `caveman` full mode for chat by default. Keep code, documentation, commits, issues, reviews, and other persisted artifacts in normal professional prose.
- For new behavior, use `lean-build` and `tdd`.
- For unknown failures, use `investigate-first` or `diagnosing-bugs`.
- For schema, API, protocol, or configuration transitions, use `migration`.
- Before completion, use `code-review`, then `verify-and-stop`.
- Preserve evidence provenance, conservative event matching, observation history, source traceability, and patient privacy.

## Model routing

Use capability tiers so this policy remains portable across Codex, Claude, and other agent platforms.

### Judgment tier

Use the strongest available reasoning/coding model for architecture, specifications, implementation plans, plan correction, code review, verification, and final synthesis.

- Codex: `gpt-5.6-sol` with `high` reasoning.
- Claude or another platform: its strongest available reasoning model with the equivalent high-reasoning setting.

### Balanced worker tier

Use a balanced coding model for normal or difficult implementation, integrations, migrations, and debugging.

- Codex: `gpt-5.6-terra`.
- Claude or another platform: its current balanced coding model.

Escalate a worker to this tier when work crosses modules, changes behavior, handles security or data integrity, or has an uncertain diagnosis.

### Fast worker tier

Use a fast, lower-cost model for bounded low-risk work such as mechanical edits, fixtures, straightforward tests, and documentation updates.

- Codex: `gpt-5.6-luna`.
- Claude or another platform: its current fast coding model.

Escalate immediately if the task becomes ambiguous, architectural, security-sensitive, or behaviorally broad.

## Agent efficiency

- Delegate only bounded independent work with exact acceptance criteria.
- Give workers the minimum sufficient context and relevant file paths.
- Prefer the fast tier for mechanical work, the balanced tier for substantive implementation, and the judgment tier for decisions and gates.
- Keep planner, implementation worker, reviewer, and verifier independent when concurrency allows.
- Reuse current verified results and avoid duplicate exploration or duplicate reviews.
- Token savings must never weaken tests, provenance, security, review, or verification.

## Agent skills

### Issue tracker

Issues and specifications live in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Use single-context domain documentation: root `CONTEXT.md` and system-wide decisions under `docs/adr/`. See `docs/agents/domain.md`.
