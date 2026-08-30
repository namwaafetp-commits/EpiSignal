# English Brief — Design

**Date:** 2026-08-28
**Status:** Approved
**Item:** `C2`
**Depends on:** `C` AI extraction (`docs/superpowers/specs/2026-08-27-ai-extraction-design.md`)
**Phase 1 spec:** §21 Required structured extraction schema, §22 AI safety and trust rules, §29 Result card

## Goal

Every extracted signal carries an English title and a five-bullet brief in a
fixed epidemiological order, so that a reader scanning the radar learns what
happened, how many, when, how it spreads, and who says so — without opening the
article and without reading its language.

Today an extraction carries `summary`: one free-form string of up to 400
characters, written in whatever language the article was written in, with no
structure a card can rely on. A reader cannot compare two of them, and a surface
built on them cannot lay them out the same way twice.

## Position

`C2` changes what extraction writes. It changes no other stage: dedupe still
selects by content hash, geocoding still reads `ai_extraction.locations`,
clustering still reads what geocoding resolved, and the scheduler still calls the
same seven stages in the same order.

It is sequenced ahead of `E` deliberately. `E` renders briefs; if `E` were built
first, the corpus would grow in the old shape and every article in it would have
to be paid for a second time. Extraction costs money once. Getting the shape
right before the corpus grows is the cheaper order.

## Vocabulary

`CONTEXT.md` is the naming authority. This item introduces two words and one
qualifier, which the plan adds to that file.

**Brief**:
The five-bullet English summary of a signal, written to be scanned. One brief per
signal, always five bullets, always in the same order.
_Avoid_: summary, which named the free-form string this replaces; abstract;
digest.

**Slot**:
One of the five fixed questions a brief answers, identified by name and fixed in
position. A slot is a position in a brief. It is never a rung of the model
ladder, which is a *tier*, nor a step of the pipeline, which is a *stage*.
_Avoid_: section, field, bullet.

**English title**:
The article's own headline rendered in English. Stored beside the publisher's
headline, never over it.

## Decisions

### The brief has five slots, in a fixed order

The slots are the questions an epidemiologist asks first, in the order they are
asked:

| Position | Slot | Answers |
| --- | --- | --- |
| 1 | `what_where` | Which disease, in which place. |
| 2 | `counts` | Cases and deaths, as the article states them. |
| 3 | `timing` | When it happened, and what date the data is as of. |
| 4 | `spread` | Local or imported transmission, hospitalizations, severity. |
| 5 | `reporting` | Who reported it, official or media, and what is unverified. |

Fixed slots make two briefs comparable and make a card's layout identical on
every signal. A model free to choose its own five points produces five different
kinds of card and nothing a reader can scan down a column.

### A silent article produces a stated absence, never a filled slot

Most articles support two or three slots. A model told to always produce five
bullets, given an article that supports three, will invent two — and this
project's hardest rule is that nothing is inferred, estimated, or carried over
from general knowledge.

So a slot the article does not address is stored with `reported: false` and text
that says what is missing: *No case count reported.* That is not filler. To an
epidemiologist, an outbreak report with no case count is a different object from
one with a count, and the brief should say which one it is reading.

### Translation stops at the source span

Every count and every transmission flag carries a `source_span`, and
`check_grounding` requires that span to occur verbatim in the article's own text.
A translated span would not be found, and the extraction would be rejected.

That is the safety property, not an obstacle: translation may touch the prose a
human reads and may never touch the evidence a check verifies. Spans stay in the
language the publisher wrote. The brief and the English title are English.

### One call, not two

The model that reads the article writes the English title and the five bullets in
the same response that carries the counts. Cost per article is one call before
this item and one call after it; only the output grows, by a title and five short
lines.

A separate translation pass would double the requests, double the failure modes,
and introduce a second model's reading of a document the first model has already
read.

Translation never triggers escalation. `CONTEXT.md` already fixes this:
escalation is a response to a rejected answer, never to a document's language.

### The brief replaces the paragraph, it does not join it

`Extraction.summary` is removed. Keeping a paragraph beside the brief would pay a
model to state the same facts twice and would leave two summaries free to
disagree with each other.

`signals.summary` — the column — survives, and holds the five bullets joined by
newlines in slot order. Nothing that reads that column breaks.

### The stored extraction carries a version, and the code writes it

`ai_extraction` gains `extraction_schema_version`, stamped by the repository at
the moment of writing. The model never authors it: a version a model can choose
is a version that lies as soon as the model is confused.

Rows written before this item carry no version and are read as version 1. This
needs no migration, because `ai_extraction` is already JSONB.

### A re-extracted signal returns to `extracted`

A second extraction can find different places than the first. A row left at
`matched` with new locations would desync the event it is attached to, silently.

So the backfill sets `processing_status` back to `extracted`, and the next daily
run geocodes and matches it again through the paths that already exist. The cost
is that a backfilled signal is briefly detached from the surface; the benefit is
that no event is ever built on locations that no longer exist.

Signals at `needs_review` are not backfilled. A human owes them a decision, and
`M` is the item that collects it.

## The schema

```python
EXTRACTION_SCHEMA_VERSION = 2
BRIEF_SLOT_COUNT = 5
BRIEF_POINT_MAX_CHARACTERS = 200
TITLE_MAX_CHARACTERS = 300


class BriefSlot(StrEnum):
    WHAT_WHERE = "what_where"
    COUNTS = "counts"
    TIMING = "timing"
    SPREAD = "spread"
    REPORTING = "reporting"


class BriefPoint(BaseModel):
    slot: BriefSlot
    text: str = Field(min_length=1, max_length=BRIEF_POINT_MAX_CHARACTERS)
    # False means the article was silent and `text` says so.
    reported: bool


class Extraction(BaseModel):
    signal_type: SignalType
    source_language: str | None = None          # ISO 639-1, lowercase, or null
    title_english: str = Field(min_length=1, max_length=TITLE_MAX_CHARACTERS)
    brief: tuple[BriefPoint, ...]               # exactly five, in slot order
    disease: NamedEntity | None = None
    pathogen: NamedEntity | None = None
    locations: tuple[ExtractedLocation, ...] = ()
    epidemiology: Epidemiology = Epidemiology()
    dates: ExtractedDates = ExtractedDates()
    transmission: Transmission | None = None
    confidence: float = Field(ge=0.0, le=1.0)
```

`summary` is gone. Everything else keeps its current meaning and its current
validators. The prompt continues to be generated from
`Extraction.model_json_schema()`, so the schema stays the one source of truth for
what the model is asked to return.

`source_language` is a two-letter lowercase code or null. Null means the model
was unsure, and unsure is recorded rather than guessed.

## The prompt

`EXTRACTION_RULES` gains four rules and loses none:

- Write `title_english` and every `text` in English. Translate; do not
  transliterate. `title_english` is always populated: for an article already
  written in English it is that article's own headline, unchanged apart from
  collapsed whitespace.
- Return exactly five brief points, one per slot, in the order the schema lists.
- A slot the article does not address gets `reported: false` and one short line
  saying what is not reported. Never fill a slot from outside the article.
- Copy every `source_span` word for word in the article's own language. Do not
  translate a span.

## Validation order

There is no separate shape function to extend: shape is what `parse_extraction`
already delegates to Pydantic, and arithmetic is the only check layered on top
of it. The brief's rules join it there, as a model validator on `Extraction`:

1. Exactly `BRIEF_SLOT_COUNT` points.
2. One point per slot, no duplicates, in the enum's order.
3. Non-blank text on every point, including `reported: false` points.

A violation raises `ValidationError`, which `parse_extraction` already converts
to `Rejected(RejectionReason.SHAPE, ...)`. The existing ladder escalates it and,
if the next tier also fails, the signal lands in `needs_review`. Nothing is
salvaged and nothing is re-ordered on the model's behalf.

`check_privacy` currently scans `extraction.summary`. It scans `title_english`
and every brief `text` instead, because those are the fields a person's name or
telephone number would now travel in.

## Persistence

`record_extraction` writes what it writes today, plus:

- `ai_extraction`: the dumped extraction with `extraction_schema_version` added
  by the repository.
- `summary`: the five `text` values joined by `"\n"` in slot order.

`signals.title` is not touched. The English title lives in `ai_extraction` and is
read from there by whatever renders a card.

### Reading what we already stored

`Extraction` forbids unknown keys, and `events/repository.py` validates stored
`ai_extraction` payloads straight back into it when it assembles a cluster. Both
of this item's storage changes would break that read: the version key is an
unknown key, and a row written before this item has no `brief` at all.

So the strict model stays strict for what a model returns, and a second model
reads what we already wrote:

```python
class StoredExtractionPayload(Extraction):
    """A stored extraction, read back. Tolerant where the strict model is not."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    title_english: str | None = None
    brief: tuple[BriefPoint, ...] = ()
```

It subclasses `Extraction`, so anything typed to accept an extraction accepts
one of these. Strict on the way in, tolerant on the way back: a model that omits
a brief is rejected, and a row we wrote last week is still readable.

Until the backfill runs, a version 1 row read this way carries no brief. That is
visible rather than hidden — `brief` is empty, and the surface says so.

## The backfill command

`pnpm extract:backfill` — `episignal_backend.backfill_runner`.

Selects signals where all of the following hold: `processing_status` is one of
`extracted`, `geocoded`, `matched`, or `published`; `ai_extraction` is not null;
the stored `extraction_schema_version` is absent or below
`EXTRACTION_SCHEMA_VERSION`; and `raw_text` is not null. Ordered by
`first_seen_at`, oldest first.

Bounded by the same `Guards` the extraction pass uses —
`ai_max_requests_per_run` and `ai_max_cost_usd_per_run` — and by a `--limit`
argument. Every request is costed into `ai_requests` exactly as a first
extraction is.

Each successful re-extraction goes through `record_extraction`, which returns the
row to `extracted`. A rejected re-extraction leaves the existing extraction in
place: a backfill never destroys a good old answer to store a bad new one.

The command prints one result line in the shape the other runners print, and
exits non-zero if any signal failed.

It is not wired into the daily chain. A future prompt change must not be able to
silently re-extract a corpus of thousands.

## Cost

One call per article, unchanged. Output grows by roughly 400 characters per
article. The backfill is a one-off over a corpus currently in the dozens,
bounded by the per-run cost guard.

## Acceptance

1. An extraction of a non-English article stores an English title and five
   English bullets while its source spans remain in the original language and
   grounding passes.
2. A model answer with four points, six points, a duplicated slot, or slots out
   of order is rejected as `shape` and never stored.
3. A slot the article does not address is stored with `reported: false` and
   non-blank text.
4. `signals.summary` holds the five bullet texts, newline-joined, in slot order.
5. Every newly written `ai_extraction` carries the current
   `extraction_schema_version`.
6. `pnpm extract:backfill --limit N` re-extracts only rows below the current
   version, respects the cost guard, returns each to `extracted`, and leaves
   `needs_review` rows alone.
7. `corepack pnpm verify` exits 0, and the run is quoted in the completion
   report.

## Out of scope, deliberately

- Translating or storing a translated `raw_text`. Phase 1 §52 governs what
  article text may be stored, and a translation is a derived work of the whole
  article rather than a fact read out of it.
- A multilingual user interface. The brief is English; the product is English.
- Per-language model routing or a language-aware ladder. `CONTEXT.md` forbids
  escalating on language.
- `events.ai_summary`. An event's summary is written from many signals and
  belongs to the item that assembles it, not to this one.
- Anything the radar renders. That is `E`.
