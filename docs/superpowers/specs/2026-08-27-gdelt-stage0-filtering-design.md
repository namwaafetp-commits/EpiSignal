# Stage 0: Deduplication and Rule Filtering — Design

**Date:** 2026-08-27
**Status:** Approved
**Sub-project:** B of `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`
**Depends on:** Sub-project A, the GDELT discovery connector (merged to `main` on 2026-08-27)

## Goal

Reject syndicated copies and obviously irrelevant articles deterministically,
before any AI call, so that sub-project C pays for inference only on documents
that are plausibly about a real public health event and that no other row
already represents.

This slice ends when a discovery run stops fetching pages it can rule out from
metadata alone, and when the two syndicated copies of one measles story in
`gdelt_artlist.json` resolve to one primary signal and one linked duplicate.

The live GDELT response recorded in sub-project A carried four copies of that
story; two were committed to the fixture. The fixture is the contract the tests
assert against.

## Out of scope

Explicitly excluded, each its own later sub-project:

- every AI call, including classification, extraction, and escalation (C);
- story clustering across *different* articles about the same event, event
  matching, and the two scores (D);
- the Signal Radar API, its UI, and the admin monitoring view (E);
- the model benchmarking harness (F).

This slice groups the same article republished. It does not group two different
articles about the same outbreak; that is sub-project D and a different
question.

Nothing here writes to `events`, `event_signals`, `event_observations`, or
`event_locations`. Nothing here calls an AI model or computes an embedding.

## The two errors and their asymmetry

Stage 0 is a pair of filters, and each has a failure mode with a different
cost. The design is shaped by that asymmetry rather than by accuracy in the
abstract.

**Discarding a real outbreak is unrecoverable.** An article rejected before its
page is fetched leaves no body text, no extraction, and no signal. If the
rejection was wrong, nothing downstream can notice. A wrongly *kept* article
costs one page fetch and one cheap comparison. The relevance filter is
therefore negative-only: an article is rejected when it matches an explicit
exclusion, never for failing to prove itself relevant.

**Merging two independent reports destroys evidence.** Two outlets reporting the
same outbreak separately are corroboration, and corroboration is the raw
material of `evidence_score`. Collapsing them into one signal deletes that and
leaves no trace. Carrying a duplicate that should have been merged is visible
and correctable. Near-duplicate matching therefore requires agreement on both
title and body, which is the architecture's conservative-matching invariant
applied one layer below event matching.

## Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Placement | A pre-fetch relevance filter inside `run_discovery`, and a post-store dedup pass in its own command | The ladder invariant states that deterministic checks run before network fetches and that both run before any AI call. Syndication detection needs body text and so cannot precede the fetch; title and domain rejection needs no body and so should. Splitting the stage is what lets each half sit at the rung where it is cheapest. |
| Filter posture | Negative-only: title exclusion patterns and a domain blocklist | A positive requirement would reject local-language reporting whose headline carries no recognisable disease word, which is the material sub-project A explicitly refused to discard. |
| Filter ordering | Before the per-run article cap, after the seen-URL drop | Filtering after the cap would spend the budget on articles about to be discarded. Filtering before the seen-URL drop would evaluate rules against rows already stored. |
| Rejected sightings | A dedicated table, not a signals row | `signals.retrieved_at` and `signals.content_hash` are both NOT NULL. A sighting rejected before its fetch was never retrieved and has no body, so storing it as a signal would require inventing both, and inventing `retrieved_at` breaks the timestamp invariant directly. |
| Rejection audit | Every rejection names the rule that caused it | False negatives are the fatal error of a surveillance radar, and an unattributed rejection cannot be reviewed. This mirrors `signals.query_rule_id`. |
| Filter rules | A table seeded idempotently from JSON | The same shape as `gdelt_query_rules`: tunable without a deployment, reviewable in Git, and a real row for `rejected_sightings.filter_rule_id` to reference. |
| Duplicate representation | The copy keeps its row and gains `duplicate_of_signal_id` | Requirement section 18 asks that syndicated copies form one signal family rather than three pieces of evidence, while keeping source URLs where useful. Deleting the copy would lose the publisher; a join table would add a table for a strictly one-primary-per-copy relation. |
| Primary selection | Earliest `first_seen_at`, then earliest `published_at`, then lowest id | The radar exists to measure detection lead time, so the sighting that earned the lead keeps it. Publisher credibility cannot discriminate here: every GDELT-registered publisher starts at `credibility_tier` unknown. |
| Match rule | Identical `content_hash`, or title similarity **and** body similarity both above threshold | Hash equality alone misses the observed case, where affiliate boilerplate differs by a line. Title similarity alone merges independent reports that share a headline. |
| Similarity method | Exact Jaccard over title tokens and over body 5-shingles | The candidate window holds at most low thousands of rows, so MinHash or SimHash would approximate a computation that is already cheap, and would make "why were these merged" harder to answer. Embeddings are excluded: they are a model call, which this stage exists to precede. |
| Survivor status | `normalized` | The value is already declared in `ProcessingStatus` and no code writes it today, so Stage 0 can define it as "passed Stage 0" without inventing vocabulary, and sub-project C gets a single-value selector. |

## Schema change

Revision `20260827_0004`:

```text
signals    + duplicate_of_signal_id  uuid null fk -> signals(id) on delete set null
             index on (duplicate_of_signal_id)

processing_status_values += 'duplicate'
             the check constraint is dropped and recreated; the vocabulary is
             stored as values, not native enum labels

new table  filter_rules
             id           uuid pk
             rule_group   text not null      title_exclusion | domain_blocklist
             pattern      text not null
             label        text not null
             active       boolean not null default true
             created_at, updated_at
             unique (rule_group, pattern)

new table  rejected_sightings
             id              uuid pk
             url             text not null
             canonical_url   text not null unique
             title           text not null
             domain          text not null
             gdelt_seen_at   timestamptz null
             rejected_at     timestamptz not null
             filter_rule_id  uuid null fk -> filter_rules(id) on delete set null
             created_at, updated_at
             index on (filter_rule_id)
             index on (rejected_at)
```

`rejected_sightings.canonical_url` is unique and a re-sighting is inserted with
conflict-do-nothing, so the same article seen in three consecutive windows
records one row.

The filter deliberately does not read `rejected_sightings` to skip work. Rules
are matched in memory and cost nothing, so a retuned rule lets a previously
rejected URL through on its next sighting rather than requiring the table to be
cleaned first.

`ondelete SET NULL` on `filter_rule_id` matches `signals.query_rule_id`: a
retired rule must not take its audit trail with it.

## Architecture

```text
packages/backend/src/episignal_backend/ingestion/
  protocol.py           + DiscoveryRepository filter methods, + DedupeRepository
  documents.py          + FilterRule, + Rejection, + ComparableSignal
  filtering.py          pure: article metadata + rules -> rejecting rule or None
  similarity.py         pure: title and body similarity
  dedupe.py             run_dedupe - imports neither SQLAlchemy nor httpx
  discovery.py          run_discovery gains the pre-fetch filter step
  repository.py         + rule and rejection methods, + SqlAlchemyDedupeRepository
packages/backend/src/episignal_backend/models/discovery.py
                        + SignalFilterRule, + RejectedSighting
packages/backend/src/episignal_backend/models/signal.py
                        + duplicate_of_signal_id
packages/backend/src/episignal_backend/seeds.py
                        + filter rule seeding
packages/backend/src/episignal_backend/dedupe_runner.py
database/seeds/filter_rules.json
```

`filtering.py` and `similarity.py` are pure functions over committed fixtures,
matching how `extract.py` and `locale.py` already work. `dedupe.py` depends only
on Protocols, so the whole decision path is exercised with in-memory fakes, no
database and no network. Neither new module opens a socket.

### Boundaries

```python
class DiscoveryRepository(Protocol):
    ...
    def filter_rules(self) -> Sequence[FilterRule]: ...

    def record_rejection(self, rejection: Rejection) -> None: ...


class DedupeRepository(Protocol):
    def pending(self, *, limit: int) -> Sequence[ComparableSignal]: ...

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> Sequence[ComparableSignal]: ...

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None: ...

    def mark_normalized(self, signal_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
```

DTOs are named apart from the tables they load from, as `QueryRule` already is
from `GdeltQueryRule`: the DTO `FilterRule` loads from the model
`SignalFilterRule`, and the DTO `Rejection` is written to `RejectedSighting`.
`ComparableSignal` serves both the queue and the candidate set because the two
carry the same fields; only the query that produces them differs.

`DedupeRepository` is a separate Protocol rather than more methods on
`DiscoveryRepository` because the dedup pass never discovers, never fetches, and
never registers a publisher. A pass that reads stored signals and writes their
status has no business holding a handle that can open a GDELT query.

### Normalization

`normalize_title` applies NFC, casefolds, drops publisher furniture following a
spaced dash — hyphen, en dash, or em dash — strips punctuation, and returns a
token set. The furniture rule is what makes the two fixture headlines compare
equal: GDELT titles carry the affiliate name and a bracketed channel number, and
sub-project A recorded exactly that.

Body normalization collapses whitespace and casefolds, then yields the set of
overlapping word 5-shingles. Similarity is Jaccard in both cases: the size of
the intersection over the size of the union, with two empty sets treated as no
match rather than a perfect one.

## Data flow

### Gate 1, inside `run_discovery`

1. Load active filter rules once per run alongside the query rules. Compile
   each title pattern; a pattern that will not compile is skipped, logged, and
   counted, and the run continues.
2. Discover and canonicalize as today.
3. Drop canonical URLs already stored, as today.
4. Evaluate each survivor against the rules. `evaluate` returns the first
   matching rule or `None`. Title patterns are matched case-insensitively
   against the GDELT title, which is the only title that exists at this rung:
   the publisher's `og:title` is preferred everywhere else, but reading it
   requires the fetch this gate is trying to avoid. Domain rules match the host
   exactly or as a dotted suffix, so `example.com` also rejects
   `news.example.com` but never `notexample.com`.
5. Record each rejected sighting with its rule and drop it. No page is fetched
   and no signal row is written.
6. Cap the survivors at the per-run limit, oldest sighting first, as today.
7. Fetch, extract, resolve the publisher, and store, as today.

### Gate 2, `run_dedupe`

1. Select signals with `processing_status` `fetched` and `raw_text` not null,
   oldest `first_seen_at` first, up to the batch size. Stubs are excluded by the
   `raw_text` condition and stay in sub-project A's retry path.
2. For each pending signal, load candidates: every signal with `raw_text` not
   null that either shares its `content_hash` or has a `first_seen_at` inside
   the comparison window. Candidates are drawn regardless of processing status,
   so a copy arriving today still matches a primary normalized yesterday.
   Candidates already marked `duplicate` are resolved to their primary before
   comparison.
3. Decide. An identical `content_hash` at a different URL is a duplicate
   outright. Otherwise compute title similarity; only if it clears its threshold
   compute body similarity; only if both clear is the pair a duplicate.
4. Among a matched pair, the primary is the earlier `first_seen_at`, then the
   earlier `published_at`, then the lower id. The other row is marked
   `duplicate` with `duplicate_of_signal_id` set to the primary. If the chosen
   primary is itself a duplicate, the pointer is flattened to its primary, so a
   pointer never leads to another pointer.
5. A signal that matches nothing is marked `normalized`.
6. Commit per signal, rolling back and counting a failure without abandoning the
   batch.

Re-running the command is a no-op: only `fetched` rows are selected, and step 5
leaves nothing in that state.

## Error handling

| Condition | Handling |
| --- | --- |
| A title pattern will not compile | Skip that rule, log it, count `rules_invalid`, continue. One malformed rule cannot silence the other rules or halt discovery. |
| No filter rules are seeded | Discovery runs unfiltered and logs that it is doing so. An empty rule set is a valid configuration, not an error; the alternative is a seeding accident silently stopping discovery. |
| Recording a rejection fails | Roll back, count `failed`, keep the article as a candidate. A lost audit row must not also lose the article. |
| No dedup candidates exist | Mark `normalized`. The first article about an outbreak has nothing to match and is the most valuable row in the table. |
| A candidate has null `raw_text` | Skip the pair. A stub cannot be compared on body, and comparing on title alone is the merge this design rejects. |
| Marking a signal fails | Roll back that signal, count `failed`, continue the batch, matching `run_discovery`. |
| The primary resolves to a chain | Flatten to the terminal primary. A cycle is impossible because the primary is always strictly earlier by a total order. |

## Testing

Test-driven throughout, per `AGENTS.md`.

**Pure, no database, no network.** `filtering.py` is tested table-driven:
metaphorical titles are rejected, a title naming a disease is kept, a
blocklisted domain is rejected as an exact host and as a subdomain, a lookalike
domain is not, and an uncompilable pattern is skipped without failing the run.
`similarity.py` is tested for title normalization on the committed
`gdelt_artlist.json` fixture, whose two Telemundo copies of one measles story
were kept for exactly this purpose: their headlines are identical up to the
affiliate furniture, `- Telemundo Dallas ( 39 )` against
`- Telemundo New York ( 47 )`. GDELT returns no body text, so body similarity is
tested against its own committed text fixtures rather than that file.

**The decisive negative test.** Two independent outlets, same headline,
different bodies, must remain two signals. This is the case that protects
corroboration, and it is the one an over-eager threshold breaks first.

**Fakes.** `run_dedupe` is exercised against an in-memory repository for primary
selection order, pointer flattening, idempotent re-runs, exclusion of stubs, and
per-signal failure isolation. `run_discovery` gains tests that the filter runs
before the cap and that a rejected article produces no `retrieve` call.

**Database.** Integration tests cover the new tables, the self-referencing
foreign key, the widened `processing_status` constraint, and idempotent filter
rule seeding.

**Unchanged.** WHO and ECDC ingestion and the existing discovery tests must
continue to pass untouched.

## Configuration

```text
EPISIGNAL_STAGE0_TITLE_SIMILARITY         0.90
EPISIGNAL_STAGE0_BODY_SIMILARITY          0.80
EPISIGNAL_STAGE0_SHINGLE_SIZE             5
EPISIGNAL_STAGE0_CANDIDATE_WINDOW_HOURS   72
EPISIGNAL_STAGE0_BATCH_SIZE               200
```

The thresholds are configuration because they are the two numbers most likely to
need tuning against real traffic, and because the architecture requires matching
weights and thresholds to stay configurable rather than compiled in.

The candidate window is 72 hours because syndication is immediate: the copies
in sub-project A's live response shared a `seendate` to the quarter hour. An
exact `content_hash` match is compared regardless of age, so a late
republication of unchanged text is still caught.

## Commands

```powershell
pnpm db:migrate          # applies 20260827_0004
pnpm db:seed             # upserts filter rules alongside queries, diseases, sources
pnpm discover:gdelt      # discovery, now filtering before it fetches
pnpm dedupe:signals      # one dedup pass over fetched signals
```

`pnpm dedupe:signals` prints counts only, matching `discover_runner.py`.

## Acceptance criteria

- An article matching a title exclusion or a blocklisted domain costs no page
  fetch and no signal row.
- Every rejection is recorded with the rule that caused it and is queryable.
- A retuned rule admits a previously rejected URL on its next sighting without
  manual cleanup.
- The two syndicated copies in the fixture resolve to one primary and one
  duplicate, each keeping its own publisher and original URL.
- Two independent articles sharing a headline but not a body remain two signals.
- The primary is the earliest sighting, and no `duplicate_of_signal_id` points
  at a row that is itself a duplicate.
- A stub is never selected, never compared, and never marked.
- Re-running the dedup pass changes nothing.
- No AI model is called and no embedding is computed anywhere in this slice.
- WHO and ECDC ingestion is unchanged and still passes its tests.
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and
  `uv run mypy apps/api/src packages/backend/src` all pass.

## Primary references

- `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`
- `docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md` — the slice this
  one extends, and the source of the syndication and rate-limit observations.
- `EpiSignal_Phase1_AI_Agent_Handoff.md` section 18, duplicate signal detection.
