# Handoff — Stage 0 deduplication and rule filtering

**Date:** 2026-08-27
**Branch:** `feat/gdelt-stage0`
**Worktree:** none. Work in the main checkout, `D:\Projects\Side Project\EpiSignal`.
**State:** Design and implementation plan are written, reviewed, and committed.
No implementation code exists yet. Task 1 of 13 is the next thing to do.

## Start here

Read, in order:

1. this file;
2. `AGENTS.md`;
3. `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the umbrella
   that fixes what each sub-project covers, and the authority when any other
   document disagrees with it;
4. `docs/superpowers/specs/2026-08-27-gdelt-stage0-filtering-design.md` — the
   design you are implementing;
5. `docs/superpowers/plans/2026-08-27-gdelt-stage0-filtering.md` — the plan,
   thirteen test-driven tasks with the code in each step.

Then execute the plan task by task. Every task is red first: write the failing
test, run it, watch it fail for the stated reason, implement, watch it pass,
commit. Do not batch tasks together, and do not write implementation before its
test.

## Windows environment

- Python commands run through `uv run`. Do not activate a virtualenv by hand.
- **`pnpm` is not on `PATH`.** Use `corepack pnpm ...`. The plan writes commands
  as `pnpm db:migrate` and so on for readability; type `corepack pnpm db:migrate`.
- PowerShell 7 is absent. Commands run under Windows PowerShell 5.1, which has
  no `&&`, no ternary, and no `??`.
- `uv` is 0.12.5.

## Current git state

`main` holds sub-project A, merged this morning:

```text
c960b2c Merge branch 'feat/gdelt-discovery'
bddda95 docs: add sub-project A reportback
8745923 chore: verify live GDELT discovery, document commands, and finalize sub-project A
```

`feat/gdelt-stage0` branches from `c960b2c` and holds three documentation
commits and nothing else:

```text
4cc1571 docs: plan the Stage 0 filtering and deduplication implementation
3564abc docs: correct the Stage 0 spec against the committed fixture
2bd3a8f docs: design Stage 0 deduplication and rule filtering
```

Nothing on this branch or on `main` has been pushed. `origin/main` is 49 commits
behind local `main`. Do not rebase onto `origin/main` and do not treat it as a
base.

A second worktree exists at `.worktrees/ingestion` on `feat/who-don-ingestion`.
That branch is merged into `main` and the worktree is stale. Leave it alone; it
is not yours to remove.

## Verified baseline

Run before you start, so that any later failure is yours and not inherited:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
```

Expected: 296 passed, `All checks passed!`, `83 files already formatted`,
`Success: no issues found in 47 source files`.

## What you are building

Stage 0 is two gates on either side of the existing page fetch.

**Gate one** is a negative-only relevance filter inside `run_discovery`. It sees
only GDELT metadata — url, title, domain, language, country, sighting time — and
rejects an article when it matches an explicit title exclusion or a blocklisted
domain. A rejection writes a `rejected_sightings` row naming the rule and costs
no page fetch. It runs after the seen-URL drop and **before** the per-run cap, so
the run's budget is spent on articles worth having.

**Gate two** is a new `run_dedupe` pass over stored signals, behind
`pnpm dedupe:signals`. It marks each signal `normalized` or `duplicate`, and a
duplicate carries `duplicate_of_signal_id` pointing at the copy that was seen
first.

## The two rules you must not soften

Both gates are shaped by the asymmetry of their errors. If you find yourself
adjusting a threshold to make a test pass, stop and re-read this section.

**Never reject an article for failing to prove itself relevant.** A wrongly
rejected article leaves no body, no extraction, and no signal, and nothing
downstream can notice it is missing. A wrongly kept article costs one page
fetch. The filter is negative-only. Do not add a rule requiring a disease word
in the title: local-language reporting with poor metadata is precisely what this
system exists to catch.

**Never merge on the title alone.** Two outlets reporting the same outbreak
independently are corroboration, and corroboration is what `evidence_score` will
be built from in sub-project D. Merging them deletes it with no trace. A
near-duplicate needs an identical `content_hash`, or agreement on **both** title
and body.

The other invariants, from the architecture document:

- The publisher is the source of record. GDELT is never a publisher.
- `published_at`, `first_seen_at`, `retrieved_at`, `gdelt_seen_at` are four
  different facts. Never fill one from another. A missing one stays NULL.
- Cheap before expensive: deterministic checks before network fetches, and both
  before any AI call.
- Failures stay visible. Every signal carries a processing state.

## Traps found while planning

These were caught in review before the plan was committed. They are recorded so
you do not rediscover them the hard way.

**The fixture holds two syndicated copies, not four.** The live GDELT response
in sub-project A carried four Telemundo copies of one measles story; two were
committed to `packages/backend/tests/fixtures/gdelt_artlist.json`, alongside one
unrelated Scottish article. The fixture is the contract.

**Title furniture is separated by a spaced hyphen, not an em dash**, and it
cannot be stripped by dropping everything after the separator. The third fixture
title, `How a near - fatal illness inspired a Highlander musical voyage`,
contains a spaced hyphen inside the headline. Task 6 drops the tail only when it
is six words or fewer, which is why `Telemundo New York ( 47 )` goes and
`fatal illness inspired a Highlander musical voyage` stays.

**Body similarity is sensitive to fixture length.** Body B strictly extends body
A, so their Jaccard similarity is exactly `shingles(A) / shingles(B)`. The
fixtures in Task 6 are sized to land near 0.88 against a 0.80 threshold. If that
test fails, lengthen the shared text. Do not lower the threshold.

**`FakeSession` in `test_discovery_repository.py` wraps raw values itself.** Pass
`[[row]]`, not `[FakeResult([row])]`. Its `FakeResult` has no `scalars()`; Task 8
adds it.

**The `processing_status` vocabulary is a check constraint, not a native enum.**
Adding `duplicate` means dropping and recreating
`ck_signals_processing_status_values`. Task 4 step 2 verifies that name against
the live database before the migration depends on it.

## Out of scope — do not build these

- **Any AI or embedding call.** Stage 0 exists to run before the first one. If a
  task seems to need a model, you have misread it.
- **Story clustering across different articles**, event matching, and the two
  scores. That is sub-project D.
- **Writes to `events`, `event_signals`, `event_observations`, `event_locations`.**
  Nothing in this slice touches them.
- **Changes to WHO or ECDC ingestion.** It is working and merged. Its tests must
  still pass untouched.

## Definition of done

The acceptance criteria at the end of the plan, all of them, plus the four gates
above passing. Then run `superpowers:finishing-a-development-branch` rather than
merging on your own initiative — `main` is unpushed and the merge style here is
`--no-ff`, matching `Merge branch 'feat/gdelt-discovery'`.

## If you get stuck

`docs/superpowers/plans/2026-08-27-gdelt-discovery.md` is the plan sub-project A
was built from and the closest model for how these tasks are meant to read.
`reportback.md` is A's ledger, including which commit did what.
