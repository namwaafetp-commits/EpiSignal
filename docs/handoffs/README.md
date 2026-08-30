# Handoff archive

One file per completed roadmap item, named `YYYY-MM-DD-<id>.md`, holding the
briefing that was active while that item was built.

`HANDOFF.md` at the repository root always describes the item being built right
now. Before it is retargeted it is copied here, never overwritten. A briefing
records why an item was built the way it was — its inherited constraints, its
invariants, and the follow-ups it carried forward — and that reasoning is worth
more after the item ships than before.

Completion reports are a different artifact and live in `docs/reports/`. A
briefing says what the worker was told; a report says what the worker did.
