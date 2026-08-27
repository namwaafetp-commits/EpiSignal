# AI Classification, Extraction, and Cost Accounting — Design

**Date:** 2026-08-27
**Status:** Proposed
**Sub-project:** C of `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`
**Depends on:** Sub-project A (GDELT discovery) and Sub-project B (Stage 0 filtering and deduplication), both merged to `main` on 2026-08-27

## Goal

Turn a stored, deduplicated news article into schema-validated epidemiological
facts that are traceable to the words of the article, and record what every
model request cost.

This slice ends when a signal with `processing_status = 'normalized'` has been
judged relevant or not, when a relevant one carries a validated extraction in
`signals.ai_extraction`, and when every request made to reach that answer has a
row in `ai_requests` naming its model, its tokens, its latency, and its price.

## Out of scope

Explicitly excluded, each its own later sub-project:

- geocoding extracted place names to coordinates;
- story clustering, event matching, and event creation (D);
- `early_signal_score` and `evidence_score` (D);
- the Signal Radar API, its UI, and admin monitoring (E);
- the benchmarking harness that measures which free model is actually best (F).

Nothing here writes to `events`, `event_signals`, `event_observations`, or
`event_locations`. Nothing here writes `verification_status`. Nothing here
creates a row in `diseases` or `pathogens`: those vocabularies are reviewed and
seeded, and a model may resolve against them but never extend them.

## Cost posture

The umbrella architecture budgets roughly 90–95 percent of inference on free
OpenRouter endpoints, 5–10 percent on a low-cost paid model, and rare use of a
stronger paid model, for 0–5 USD per month.

This sub-project is built to a stricter posture, decided on 2026-08-27: all
three tiers run on free OpenRouter endpoints, and no paid model is seeded.
Expected spend is 0.00 USD.

That decision changes which resource is scarce. Under a paid ladder the binding
constraint is dollars; under a free ladder it is requests, because free
OpenRouter endpoints are rate-limited per minute and per day and can refuse or
disappear without notice. The design therefore guards both a per-run cost cap
and a per-run request cap, and treats "the provider would not answer" as a
first-class outcome distinct from "the provider answered badly".

The accounting machinery is built as though money were being spent. Prices live
on the model roster, the cost of every call is computed and stored, and the
price used is copied onto the cost row. Adding a paid tier later is a seed row,
not a code change.

## The three errors and their asymmetry

**Fabricating a fact is the worst error.** A hallucinated case count enters the
database as evidence, propagates into events and scores in sub-project D, and is
indistinguishable from a real one at every later stage. Nothing downstream can
detect it. This is the error the design spends the most to prevent, and it is
why every extracted number must carry a span of the article that contains it.

**Dropping a real outbreak is next.** A signal wrongly classified as irrelevant
is never extracted and never reaches an event. It remains in the database and
remains reviewable, so the error is recoverable, but only if someone looks.
Classification is therefore biased toward keeping: ambiguity escalates, and an
unresolved ambiguity ends as `needs_review` rather than as a silent rejection.

**Overspending is the least costly error, and the only one bounded by
construction.** A wasted request costs a slot in a daily quota. Guards stop a run
rather than letting it run away, and a stopped run resumes on the next
invocation with nothing lost.

## Decisions

1. **One command, two stages.** `pnpm extract:signals` runs classification and
   then extraction. They are separate passes over separate queues, not one call
   per signal, because they have different evidence needs and different cost
   shapes.

2. **Classification is batched; extraction is not.** Classification decides
   relevance from the title and the opening of the body, so many signals fit in
   one request. Extraction needs the whole document and produces a large
   structured object; batching it would let one malformed entry poison a response
   covering many signals, and would put the output token budget on the critical
   path.

3. **The escalation ladder is data, not code.** `ai_models` holds one row per
   tier: model id, tier, prices, active flag. A request begins at the lowest
   active tier and moves up only when a deterministic check rejects the answer.
   Swapping a dead free endpoint is a seed edit.

4. **Escalation is triggered by checks, never by taste.** The triggers are
   enumerated below and are all deterministic. Model self-reported confidence is
   one trigger among them, never the only one, and never a reason to accept.

5. **Language is not an escalation trigger.** A confident, span-supported
   extraction from a Thai, French, or Arabic report is accepted at Tier 1. The
   document's script and language never move it up the ladder on their own.
   Tier 3 exists for documents that two lower tiers could not extract, whatever
   language they are in.

6. **Every stored number names its evidence.** An extracted count is accepted
   only with a short verbatim span from the article that contains that number.
   The span is checked against the stored text, not trusted.

7. **Absence is stored as absence.** A metric the article does not state is
   `null`. A transmission characterisation the article does not make is `null`,
   never `false`. An empty object is not a finding.

8. **Resolve against the seeded vocabulary, never extend it.** A disease name is
   matched to `diseases` by canonical name, slug, or synonym, case-folded. A
   match stores `signals.disease_id`. No match stores the candidate string inside
   the extraction and leaves `disease_id` NULL.

9. **"Could not ask" and "asked and could not trust" are different outcomes.** A
   rate limit, a timeout, or an exhausted guard leaves the signal at its current
   status and writes nothing to it; the next run picks it up unchanged. A
   validated rejection at every available tier moves it to `needs_review`.

10. **Every HTTP request to a model writes a cost row, including failures.**
    Tokens spent on a rejected answer are still tokens spent. A ledger that
    records only successes understates the true cost of the ladder, which is the
    number sub-project F needs.

## What the model is asked for, and what is stored

The extraction contract follows requirements section 21, with the additions that
decisions 6 and 7 require.

```json
{
  "signal_type": "outbreak_report",
  "summary": "Health authorities report a cholera outbreak in Luanda province.",
  "disease": { "name": "Cholera", "confidence": 0.97 },
  "pathogen": { "name": "Vibrio cholerae", "confidence": 0.91 },
  "locations": [
    { "role": "primary", "country": "Angola", "admin1": "Luanda", "place_name": "Luanda" }
  ],
  "epidemiology": {
    "suspected_cases": null,
    "confirmed_cases": { "value": 327, "source_span": "327 confirmed cases" },
    "total_cases": { "value": 327, "source_span": "327 confirmed cases" },
    "deaths": { "value": 14, "source_span": "14 people have died" },
    "new_cases": null,
    "new_deaths": null
  },
  "dates": { "data_as_of": "2026-08-25", "event_date": null },
  "transmission": {
    "local_transmission": { "value": true, "source_span": "all cases were acquired locally" },
    "imported": null
  },
  "confidence": 0.94
}
```

Differences from the conceptual schema in the requirements, and why:

- Every epidemiological metric and every transmission flag is either `null` or an
  object carrying both the value and the span of the article that supports it. A
  bare number cannot be checked, and an unchecked number is a claim the system is
  making on its own behalf.
- `publication_date` is not requested. `signals.published_at` is already
  extracted deterministically from the page in sub-project A, and asking a model
  to restate it invites it to disagree with a fact we already know. `data_as_of`
  and `event_date` remain, because only the prose states those.
- `is_public_health_relevant` is not requested. Relevance was decided by the
  classification pass and is already stored on the signal; asking again produces
  a second opinion that nothing reconciles, and a stored contradiction is worse
  than a decision made once. A model that believes an article is irrelevant will
  say so through `null` metrics and a low `confidence`, both of which the checks
  already act on.
- `create_or_update_event` is not requested. Whether an event exists is
  sub-project D's decision, made from clustering and matching rules, and a model
  opinion recorded here would be read later as an input to that decision.
- `summary` is bounded to 400 characters and is the only free-text field.

Everything else the model returns is rejected: the schema forbids unknown keys.

## Validation, in order

A response is accepted only after passing every check, in this order. The first
failure is recorded as the rejection reason and drives escalation.

1. **Parse.** The response body is JSON. Text around the JSON, code fences, or a
   trailing explanation cause rejection.
2. **Shape.** It validates against the strict schema: unknown keys forbidden,
   enumerated fields drawn from the stored vocabularies, `confidence` within 0 to
   1, dates ISO-8601.
3. **Batch identity** (classification only). The set of signal ids in the
   response equals the set sent, exactly. A missing id, a repeated id, or an id
   that was never sent rejects the whole response, not the offending entry. A
   model that invents an id has lost track of which document it is answering
   about, and the remaining entries cannot be trusted either.
4. **Arithmetic.** `confirmed_cases` and `suspected_cases` may not sum above
   `total_cases`; `deaths` may not exceed `total_cases`; `new_cases` may not
   exceed `total_cases`; `new_deaths` may not exceed `deaths`. Each comparison
   applies only where both sides are present.
5. **Grounding.** For each populated metric and each populated transmission flag,
   the `source_span` must occur in the stored `raw_text` after whitespace
   collapse and case folding, and for a metric the digits of the value must occur
   inside that span. A span the document does not contain is a fabrication, and
   the extraction is rejected rather than partially salvaged.
6. **Emptiness.** A `transmission` object whose flags are all absent is stored as
   `null`. A transmission flag with a span but no value, or a value but no span,
   is a rejection.
7. **Privacy.** `summary` and every `place_name` are checked against patterns for
   email addresses, telephone numbers, and long digit runs. A match rejects the
   extraction. This is a check on what this system stores; it is not a claim
   about what the publisher wrote, and it is not a general PII detector.
8. **Confidence.** `confidence` at or above `EPISIGNAL_AI_MIN_CONFIDENCE`.

Checks 1 through 7 are properties of the answer. Check 8 is the model's opinion
of itself and is deliberately last, so that a confident fabrication is caught by
grounding before confidence is ever consulted.

## Escalation

| Trigger | Granularity |
| --- | --- |
| Transport failure, or an HTTP status the client does not retry | whole request |
| Any validation failure, checks 1 through 8 | whole request |

A classification batch escalates as a batch. An extraction escalates the single
signal it covers. Escalation moves to the next active tier in `ai_models` and
re-sends the same prompt; the ladder ends at the highest active tier or at
`EPISIGNAL_AI_MAX_TIER`, whichever is lower.

Explicitly not triggers: a non-English language, a non-Latin script, a long
document, a document with no numbers in it, or a `null`-heavy extraction. An
article that reports an outbreak without counts is a correct extraction with
`null` metrics.

When the ladder is exhausted the signal becomes `needs_review`. The reason lives
on its `ai_requests` rows, so the admin view in sub-project E can show why
without re-running anything.

## Status transitions

```text
normalized
   |  classification pass
   |-- not relevant     -> classified, public_health_relevant = false  (terminal here)
   |-- relevant         -> classified, public_health_relevant = true, relevance_score set
   \-- ladder exhausted -> needs_review

classified + public_health_relevant = true
   |  extraction pass
   |-- accepted         -> extracted, ai_extraction, ai_model, ai_processed_at, disease_id
   \-- ladder exhausted -> needs_review

any stage, provider unreachable or guard exhausted
   \-- status unchanged, nothing written, next run retries
```

`classified` with `public_health_relevant = false` is terminal for this layer, in
the same way `duplicate` is terminal for Stage 0: a correct outcome, not an
error, and still visible.

Signals with `duplicate`, `needs_review`, or `fetched` are never selected. The
selection query is the enforcement of the handoff's first invariant, and it is
tested directly.

## Schema change

Migration `20260827_0005_ai_extraction`.

**New table `ai_models`** — the escalation ladder, editable without a deployment,
in the shape of `filter_rules` and `gdelt_query_rules`.

| Column | Type | Note |
| --- | --- | --- |
| `id` | uuid | |
| `tier` | smallint | 1, 2, or 3. Ordering of the ladder. |
| `model_id` | text, unique | The provider's identifier. |
| `label` | text | Human name for the admin view. |
| `prompt_price_per_million` | numeric(12,6) | USD. `0` for a free endpoint. |
| `completion_price_per_million` | numeric(12,6) | USD. |
| `active` | boolean | An inactive row is skipped by the ladder. |

**New table `ai_requests`** — one row per HTTP request to a model.

| Column | Type | Note |
| --- | --- | --- |
| `id` | uuid | |
| `ai_model_id` | uuid, FK `ai_models` ON DELETE SET NULL | Retiring a model must not delete its spend. |
| `model_id` | text | Copied, so the row survives its roster entry. |
| `tier` | smallint | |
| `purpose` | vocabulary | `classification` or `extraction`. |
| `signal_id` | uuid, FK `signals` ON DELETE SET NULL | NULL for a batch. |
| `batch_size` | smallint | 1 for extraction. |
| `prompt_tokens` | integer, NULL | NULL when the provider returned none. |
| `completion_tokens` | integer, NULL | |
| `latency_ms` | integer | Measured around the HTTP call. |
| `http_status` | smallint, NULL | NULL when no response arrived. |
| `outcome` | vocabulary | `accepted`, `rejected`, or `unavailable`. |
| `rejection_reason` | text, NULL | The name of the first failed check. |
| `prompt_price_per_million` | numeric(12,6) | The price at the time of the call. |
| `completion_price_per_million` | numeric(12,6) | |
| `cost_usd` | numeric(12,6) | Computed, never provider-reported. |
| `requested_at` | timestamptz | |

Prices are copied onto the row because a price is a fact about a moment.
Re-pricing a model in the roster must not silently rewrite what past runs cost.

**Column on `signals`:** `disease_id`, uuid, FK `diseases` ON DELETE SET NULL,
indexed. A disease id inside a JSONB blob is a foreign key the database cannot
enforce, and a deleted disease would leave a dangling identifier with no error.

No change to `processing_status`: `classified`, `extracted`, and `needs_review`
already exist in the vocabulary, so the check constraint is untouched.

**Rollback.** `ai_requests` is a ledger. `downgrade()` refuses to run while it
holds rows unless the operator sets `EPISIGNAL_ALLOW_AI_AUDIT_LOSS=1`, and raises
with that instruction otherwise. Dropping a table of numbers nobody can recompute
is a destructive step, separately authorized rather than implied by
`pnpm db:rollback`. The check is skipped while Alembic renders offline SQL, where
there is no connection to count with and nothing is destroyed by printing a
statement.

## Architecture

```text
packages/backend/src/episignal_backend/ai/
  documents.py    contracts crossing every seam here
  protocol.py     the two Protocols below
  schema.py       the strict extraction schema, and the JSON Schema the prompt carries
  prompts.py      pure prompt construction
  validate.py     pure: parse, shape, batch identity, arithmetic, grounding, privacy
  ladder.py       pure: tier order, run guards, one climb of the ladder, cost
  classify.py     the batched relevance pass
  extract.py      the per-signal extraction pass
  openrouter.py   the httpx adapter, the only file here that opens a socket
  repository.py   the SQLAlchemy adapter, the only file here that imports SQLAlchemy
extract_runner.py CLI entry point for `pnpm extract:signals`
models/ai.py      AiModel, AiRequest
```

`documents.py`, `schema.py`, `prompts.py`, `validate.py`, `ladder.py`,
`classify.py`, and `extract.py` import neither `sqlalchemy` nor `httpx`. This is
the rule Stage 0 already follows, and it is what makes every decision testable
with in-memory fakes and no credentials.

### Boundaries

Two Protocols in `ai/protocol.py`.

```python
class ChatModel(Protocol):
    def complete(self, request: ChatRequest) -> ChatResponse: ...
```

`ChatRequest` carries the model id, the system and user messages, and the
response format. `ChatResponse` carries the raw text, the token usage, the HTTP
status, and the measured latency. It carries no cost: pricing is the ladder's
job, and a transport adapter that knew prices would have to change every time one
moved.

```python
class AiRepository(Protocol):
    def models(self) -> Sequence[ModelSpec]: ...
    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]: ...
    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]: ...
    def resolve_disease(self, name: str) -> UUID | None: ...
    def record_request(self, record: AiRequestRecord) -> None: ...
    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None: ...
    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None: ...
    def mark_needs_review(self, signal_id: UUID) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

The repository owns transactions. `classify.py` and `extract.py` call `commit`
and `rollback` and never open a session; nothing above the repository knows what
a session is.

Two adapters exist at each seam, which is what makes them real seams rather than
hypothetical ones: `OpenRouterChatModel` and the in-memory fake the tests drive at
the model seam, `SqlAlchemyAiRepository` and its fake at the storage seam. One
OpenRouter adapter covers all three tiers, because a tier is a model id and a
price, not a protocol.

## Data flow

### Classification pass

1. Select up to `EPISIGNAL_AI_SIGNAL_BATCH_LIMIT` signals with
   `processing_status = 'normalized'` and a non-null `raw_text`, oldest
   `first_seen_at` first.
2. Split into batches of `EPISIGNAL_AI_BATCH_SIZE`. Each entry carries the signal
   id, the title, and an opening slice of the body, truncated at a whitespace
   boundary so that the batch stays within
   `EPISIGNAL_AI_MAX_INPUT_CHARACTERS`.
3. Check the run guards. If either the request cap or the cost cap is reached,
   stop and leave the rest for the next run.
4. Send at the lowest active tier. Record the cost row. Validate.
5. On rejection, escalate. On exhaustion, mark every signal in the batch
   `needs_review`.
6. On acceptance, write each verdict and commit the batch.

### Extraction pass

1. Select signals with `processing_status = 'classified'` and
   `public_health_relevant` true, oldest first.
2. For each: truncate `raw_text` to `EPISIGNAL_AI_MAX_INPUT_CHARACTERS` at a
   whitespace boundary, build the prompt from the schema, check the guards, send,
   record the cost row, validate.
3. On acceptance, resolve the disease name against the seeded vocabulary, store
   the extraction, the model id, the processing time, and `disease_id` when
   resolved. Commit that signal alone.
4. On exhaustion, mark it `needs_review` and commit.

One signal per transaction: a run that dies halfway leaves finished work
committed and unfinished work untouched, and re-running is safe because the
selection query no longer returns what has moved on.

## Error handling

| Condition | Result |
| --- | --- |
| 429, 500, 502, 503, 504 | Retried up to `EPISIGNAL_AI_MAX_ATTEMPTS_PER_TIER` with a delay, then treated as unavailable |
| Timeout or connection error | Same |
| 401, 403 | The run stops. A bad credential will not fix itself, and burning the request cap on it hides the cause |
| Provider unavailable at every tier | Cost rows written with `outcome = 'unavailable'`, signal untouched, next run retries |
| Validation failure at every tier | Cost rows written with `outcome = 'rejected'`, signal `needs_review` |
| No active model rows | The run stops with a message naming the empty roster |
| Guard reached | The run stops cleanly and reports how many signals were left |

The runner prints counts only. The API key, the prompts, and the article bodies
never reach stdout, matching `discover_runner.py` and `dedupe_runner.py`.

## Testing

Confirmed seams, and nothing is tested past them:

| Seam | Test file | Adapter used |
| --- | --- | --- |
| The extraction schema | `test_ai_schema.py` | none, direct validation |
| The deterministic checks | `test_ai_validate.py` | none |
| Tier order, guards, the climb, cost | `test_ai_ladder.py` | scripted fake model |
| Classification pass | `test_ai_classify.py` | fake repository, fake model |
| Extraction pass | `test_ai_extract.py` | fake repository, fake model |
| OpenRouter adapter | `test_openrouter.py` | `httpx.MockTransport` |
| Storage adapter | `test_ai_repository.py` | the `FakeSession` style in `test_dedupe_repository.py` |
| CLI | `test_extract_runner.py` | patched pass |

No test opens a socket, reads an API key, or needs a database.

Fixtures the tests assert against:

- `ai_outbreak_body.txt` — an English report with counts and deaths, whose spans
  the grounding check can find.
- `ai_multilingual_body.txt` — a non-English report of the same shape, used to
  prove that language alone does not escalate.
- `ai_ungrounded_response.json` — a well-formed response whose `source_span` does
  not occur in the body. The grounding check must reject it, and this is the
  single most important test in the sub-project.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `EPISIGNAL_OPENROUTER_API_KEY` | none | Secret. Absent means the run stops before any request. |
| `EPISIGNAL_OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | |
| `EPISIGNAL_AI_SIGNAL_BATCH_LIMIT` | 100 | Signals examined per run. |
| `EPISIGNAL_AI_BATCH_SIZE` | 20 | Signals per classification request. |
| `EPISIGNAL_AI_MAX_REQUESTS_PER_RUN` | 200 | The binding guard under a free ladder. |
| `EPISIGNAL_AI_MAX_COST_USD_PER_RUN` | 0.50 | Guards a paid tier that does not exist yet. |
| `EPISIGNAL_AI_MIN_CONFIDENCE` | 0.60 | |
| `EPISIGNAL_AI_MAX_INPUT_CHARACTERS` | 12000 | |
| `EPISIGNAL_AI_REQUEST_DELAY_SECONDS` | 1.0 | |
| `EPISIGNAL_AI_REQUEST_TIMEOUT_SECONDS` | 60.0 | |
| `EPISIGNAL_AI_MAX_ATTEMPTS_PER_TIER` | 3 | HTTP retries, not tiers. |
| `EPISIGNAL_AI_MAX_TIER` | 3 | |

## Commands

```bash
corepack pnpm db:migrate
corepack pnpm db:seed
corepack pnpm extract:signals
```

`extract:signals` accepts `--limit`, `--batch-size`, and
`--stage classify|extract|both`.

## Acceptance criteria

1. A `normalized` signal with a relevant body ends as `extracted`, carrying a
   schema-valid `ai_extraction`, an `ai_model`, and an `ai_processed_at`.
2. A `normalized` signal about a football match ends as `classified` with
   `public_health_relevant = false`, and no extraction request is made for it.
3. Signals with `duplicate`, `needs_review`, or `fetched` are never selected by
   either pass, proven by a test on the selection query.
4. A response whose `source_span` does not occur in the article is rejected, the
   signal is not written, and the ladder escalates.
5. A classification response containing an id that was not sent rejects the whole
   batch.
6. A confident, grounded extraction from a non-English article is accepted at
   Tier 1 and makes exactly one request.
7. Every request, including rejected and unavailable ones, has an `ai_requests`
   row with tokens, latency, outcome, the price used, and a computed cost.
8. A run that reaches its request cap stops, reports what remains, and leaves the
   remaining signals selectable by the next run.
9. `pnpm db:rollback` over migration 0005 refuses while `ai_requests` holds rows
   unless the audit-loss variable is set.
10. `uv run pytest`, `ruff check`, `ruff format --check`, and `mypy` all pass.

## Primary references

- `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — invariants.
- `HANDOFF.md` — the four invariants this sub-project must not break.
- `EpiSignal_Phase1_AI_Agent_Handoff.md` sections 21, 22, 51, 52.
- `docs/superpowers/specs/2026-08-27-gdelt-stage0-filtering-design.md` — the
  module and seam conventions this design follows.
