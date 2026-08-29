# Pipeline Funnel v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task by
> task. Steps use checkbox (`- [ ]`) syntax for tracking. Project skills
> `lean-build`, `tdd`, and `migration` apply throughout, per `AGENTS.md`.

**Date:** 2026-08-29
**Spec:** [2026-08-29-pipeline-funnel-v2-design.md](../specs/2026-08-29-pipeline-funnel-v2-design.md)
**Briefing:** [HANDOFF.md](../../../HANDOFF.md)

**Goal:** Decide relevance from the title with seeded keywords instead of a
model call, fetch bodies only for articles that pass, and extract one story
once instead of once per outlet.

**Architecture:** Two new chain stages (`retrieve`, `pregroup`) put the funnel
in the order the spec draws it. The keyword gate is a pure function over rows
that already have a table. Cluster extraction is the existing extraction pass
generalized from one body to a sequence of bodies, so per-article extraction
becomes the one-member case and one grounding implementation serves both.

**Tech stack:** Python 3.12, SQLAlchemy 2 ORM, Alembic, Pydantic v2,
pytest, mypy strict, ruff. Next.js/TypeScript for the one web validator
constant. Package manager: `uv` for Python, `corepack pnpm` for the workspace.

**Branch:** create `codex/pipeline-funnel-v2` in a **separate worktree** from
the head of `codex/manual-review-queue`, which carries the unmerged
prerequisite work. Never check out a feature branch in the primary tree.

**Worker contract:** test-first per task; tick the task in `STATUS.md` in the
same commit that completes it; run the scoped tests before committing; no task
edits a module it does not own. Stop after Task 19 and hand back to the
planner. Do **not** mark the roadmap item `verified`.

---

## File structure

Everything this plan creates or changes, and what each file is responsible for.

**Created**

| File | Responsibility |
| --- | --- |
| `packages/backend/src/episignal_backend/ingestion/keyword_gate.py` | The pure gate: one title, one rule set, one decision. No DB, no HTTP. |
| `packages/backend/src/episignal_backend/ingestion/retrieval.py` | The gate-and-fetch pass: selects bodyless signals, gates, fetches, promotes. Pure of SQLAlchemy. |
| `packages/backend/src/episignal_backend/retrieve_runner.py` | `pnpm retrieve:signals` entry point. |
| `database/migrations/versions/20260829_0016_filtered_status.py` | Widens the `processing_status_values` CHECK constraint with `filtered`. |
| `packages/backend/tests/test_keyword_gate.py` | Gate decisions, pass-bias, case folding. |
| `packages/backend/tests/test_retrieval.py` | The retrieval pass over fakes. |
| `packages/backend/tests/test_retrieve_runner.py` | Runner argument parsing and exit codes. |
| `packages/backend/tests/test_ai_cluster.py` | Cluster extraction acceptance, fallback, member marking. |
| `docs/adr/2026-08-29-representative-carries-cluster-extraction.md` | D5's decision and the condition that would reverse it. |
| `docs/reports/2026-08-29-pipeline-funnel-v2-report.md` | The completion report (Task 19). |

**Modified**

| File | Change |
| --- | --- |
| `db/types.py` | `FilterRuleGroup.TITLE_INCLUSION`, `ProcessingStatus.FILTERED`. |
| `database/seeds/filter_rules.json` | The `title_inclusion` keyword rows. |
| `ingestion/documents.py` | `GateDecision` has no home here; `StubRetrieval` is reused as-is. No change expected — verify before editing. |
| `ingestion/protocol.py` | `DiscoveryConnector.defer`, `DiscoveryRepository.gated_awaiting_retrieval` / `record_filtered` / `keyword_rules`, `PreGroupStore`. |
| `ingestion/repository.py` | The three new methods, plus the `needs_review` status filter on `stubs_awaiting_retrieval`. |
| `ingestion/gdelt/connector.py` | `defer()`. |
| `ingestion/discovery.py` | `run_discovery` stores deferred instead of retrieving. |
| `ingestion/pregroup.py` | `run_pregroup` domain function. |
| `pregroup_runner.py` | Calls `run_pregroup`. |
| `ai/schema.py` | `source_index` on grounded values, version 3, `BACKFILL_MIN_SCHEMA_VERSION`. |
| `ai/validate.py` | `check_grounding` over a sequence of bodies. |
| `ai/prompts.py` | `cluster_extraction_prompt`. |
| `ai/documents.py` | `ClusterMemberSignal`, `ExtractableCluster`, `StoredClusterExtraction`. |
| `ai/protocol.py` | `awaiting_cluster_extraction`, `record_cluster_extraction`. |
| `ai/repository.py` | Those two methods; deferral exclusion and widened status on `awaiting_extraction`; backfill floor. |
| `ai/extract.py` | `run_cluster_extraction` and the per-article fallback. |
| `schedule/documents.py` | `StageName.RETRIEVE`, `StageName.PREGROUP`. |
| `schedule/chains.py` | The new chain order. |
| `schedule/stages.py` | `_retrieve`, `_pregroup`, the unwired classification call, extract summary keys. |
| `config.py` | `pregroup_enabled` default flips to `True`. |
| `apps/web/src/lib/api-radar.ts` | `"filtered"` in `PROCESSING_STATUSES`. |
| `apps/api/tests/test_migrations.py` | Head revision assertion. |
| `package.json` | `retrieve:signals` script. |
| `CONTEXT.md` | Funnel diagram and glossary. |
| `STATUS.md` | Task ledger ticks, then the verified baseline. |
| `ROADMAP.md` | Item set to `building` in the Task 1 commit. |

---

## Before Task 1

- [ ] **Create the worktree and a clean baseline**

```bash
git worktree add ../EpiSignal-funnel-v2 -b codex/pipeline-funnel-v2 codex/manual-review-queue
```

Then, in the new worktree, copy `apps/api/.env` across from the current
worktree (it is not committed) and run:

```bash
corepack pnpm install && corepack pnpm verify
```

Expected: exit code 0. Record the commit and the test counts; Task 19 compares
against them. If this baseline is red, stop and report — do not start Task 1 on
a red tree.

---

## Task 1: The `title_inclusion` rule group and its seed

**Files:**
- Modify: `packages/backend/src/episignal_backend/db/types.py:30-32`
- Modify: `database/seeds/filter_rules.json`
- Test: `packages/backend/tests/test_seeds.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_seeds.py`:

```python
def test_the_keyword_gate_seed_carries_title_inclusion_rules() -> None:
    rules = load_filter_rules()
    inclusions = [rule for rule in rules if rule.rule_group is FilterRuleGroup.TITLE_INCLUSION]

    assert len(inclusions) >= 20
    patterns = {rule.pattern for rule in inclusions}
    assert "outbreak" in patterns
    assert "ministry of health" in patterns


def test_no_inclusion_keyword_is_short_enough_to_match_by_accident() -> None:
    # Matching is case-folded substring, so a three-character keyword would
    # pass every title containing it inside a longer, unrelated word.
    for rule in load_filter_rules():
        if rule.rule_group is FilterRuleGroup.TITLE_INCLUSION:
            assert len(rule.pattern) >= 4, rule.label


def test_every_inclusion_keyword_is_stored_case_folded() -> None:
    for rule in load_filter_rules():
        if rule.rule_group is FilterRuleGroup.TITLE_INCLUSION:
            assert rule.pattern == rule.pattern.casefold(), rule.label
```

Add `FilterRuleGroup` and `load_filter_rules` to that file's imports if they
are not already there.

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_seeds.py -v
```

Expected: FAIL — `AttributeError: TITLE_INCLUSION`.

- [ ] **Step 3: Add the rule group**

In `packages/backend/src/episignal_backend/db/types.py`:

```python
class FilterRuleGroup(StrEnum):
    TITLE_EXCLUSION = "title_exclusion"
    DOMAIN_BLOCKLIST = "domain_blocklist"
    # Positive evidence, matched as case-folded substring rather than a
    # pattern: rejection has to be precise, inclusion has to be generous.
    TITLE_INCLUSION = "title_inclusion"
```

- [ ] **Step 4: Seed the keywords**

Append these objects to the array in `database/seeds/filter_rules.json`. Do not
add disease names: the gate reads those from the `diseases` table (Task 4).

```json
  { "rule_group": "title_inclusion", "pattern": "outbreak", "label": "Context: outbreak" },
  { "rule_group": "title_inclusion", "pattern": "epidemic", "label": "Context: epidemic" },
  { "rule_group": "title_inclusion", "pattern": "pandemic", "label": "Context: pandemic" },
  { "rule_group": "title_inclusion", "pattern": "cases", "label": "Context: cases" },
  { "rule_group": "title_inclusion", "pattern": "case of", "label": "Context: case of" },
  { "rule_group": "title_inclusion", "pattern": "deaths", "label": "Context: deaths" },
  { "rule_group": "title_inclusion", "pattern": "dies of", "label": "Context: dies of" },
  { "rule_group": "title_inclusion", "pattern": "died of", "label": "Context: died of" },
  { "rule_group": "title_inclusion", "pattern": "infected", "label": "Context: infected" },
  { "rule_group": "title_inclusion", "pattern": "infection", "label": "Context: infection" },
  { "rule_group": "title_inclusion", "pattern": "quarantine", "label": "Context: quarantine" },
  { "rule_group": "title_inclusion", "pattern": "isolation ward", "label": "Context: isolation ward" },
  { "rule_group": "title_inclusion", "pattern": "suspected", "label": "Context: suspected" },
  { "rule_group": "title_inclusion", "pattern": "confirmed", "label": "Context: confirmed" },
  { "rule_group": "title_inclusion", "pattern": "vaccine", "label": "Context: vaccine" },
  { "rule_group": "title_inclusion", "pattern": "vaccination", "label": "Context: vaccination" },
  { "rule_group": "title_inclusion", "pattern": "immunisation", "label": "Context: immunisation" },
  { "rule_group": "title_inclusion", "pattern": "immunization", "label": "Context: immunization" },
  { "rule_group": "title_inclusion", "pattern": "ministry of health", "label": "Context: ministry of health" },
  { "rule_group": "title_inclusion", "pattern": "health ministry", "label": "Context: health ministry" },
  { "rule_group": "title_inclusion", "pattern": "public health", "label": "Context: public health" },
  { "rule_group": "title_inclusion", "pattern": "health authorities", "label": "Context: health authorities" },
  { "rule_group": "title_inclusion", "pattern": "world health organization", "label": "Context: WHO" },
  { "rule_group": "title_inclusion", "pattern": "health alert", "label": "Context: health alert" },
  { "rule_group": "title_inclusion", "pattern": "disease", "label": "Context: disease" },
  { "rule_group": "title_inclusion", "pattern": "virus", "label": "Context: virus" },
  { "rule_group": "title_inclusion", "pattern": "bacteria", "label": "Context: bacteria" },
  { "rule_group": "title_inclusion", "pattern": "pathogen", "label": "Context: pathogen" },
  { "rule_group": "title_inclusion", "pattern": "surveillance", "label": "Context: surveillance" },
  { "rule_group": "title_inclusion", "pattern": "transmission", "label": "Context: transmission" },
  { "rule_group": "title_inclusion", "pattern": "zoonotic", "label": "Context: zoonotic" },
  { "rule_group": "title_inclusion", "pattern": "fatality", "label": "Context: fatality" }
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest packages/backend/tests/test_seeds.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/db/types.py database/seeds/filter_rules.json packages/backend/tests/test_seeds.py ROADMAP.md STATUS.md
git commit -m "feat(gate): seed title-inclusion keyword rules"
```

Set the roadmap item to `building` and tick ledger item 1 in this commit.

---

## Task 2: The `filtered` processing status

**Files:**
- Modify: `packages/backend/src/episignal_backend/db/types.py:49-66`
- Create: `database/migrations/versions/20260829_0016_filtered_status.py`
- Modify: `apps/api/tests/test_migrations.py:30`
- Modify: `apps/web/src/lib/api-radar.ts:65-76`
- Test: `packages/backend/tests/test_schema_check.py`, `apps/api/tests/test_migrations.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_migrations.py`:

```python
def test_the_filtered_status_widens_the_check_constraint() -> None:
    sql = render_offline("upgrade", "20260829_0015:20260829_0016")
    assert "processing_status_values" in sql
    assert "'filtered'" in sql


def test_the_filtered_downgrade_returns_rows_to_fetched() -> None:
    source = _revision_source("20260829_0016_filtered_status")
    assert "processing_status = 'fetched'" in source
    assert "processing_status = 'filtered'" in source
```

Change the head assertion in `test_migrations_have_one_linear_head`:

```python
    assert scripts.get_heads() == ["20260829_0016"]
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest apps/api/tests/test_migrations.py -v
```

Expected: FAIL — head is `20260829_0015`, revision file missing.

- [ ] **Step 3: Add the status**

In `db/types.py`, inside `ProcessingStatus`, after `DUPLICATE`:

```python
    # Terminal, like DUPLICATE: the keyword gate found no evidence in the
    # title that this article concerns a public health event. The row and its
    # title are preserved so a widened keyword list can re-gate it.
    FILTERED = "filtered"
```

- [ ] **Step 4: Write the migration**

Create `database/migrations/versions/20260829_0016_filtered_status.py`:

```python
"""filtered processing status

Revision ID: 20260829_0016
Revises: 20260829_0015
Create Date: 2026-08-29

The keyword gate needs a terminal status that preserves the row:
- Expand the processing_status check constraint with 'filtered'.
- Downgrade returns filtered rows to 'fetched' before narrowing the
  constraint, so no evidence is lost and the funnel simply re-gates them.

processing_status is a VARCHAR with a CHECK constraint, not a pg enum:
db/types.vocabulary() builds sa.Enum(..., native_enum=False,
create_constraint=True). ALTER TYPE would fail here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0016"
down_revision: str | None = "20260829_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROCESSING_STATUSES = (
    "fetched",
    "normalized",
    "classified",
    "extracted",
    "geocoded",
    "matched",
    "published",
    "duplicate",
    "failed",
    "needs_review",
    "dismissed",
    "filtered",
)

PREVIOUS_PROCESSING_STATUSES = tuple(
    status for status in PROCESSING_STATUSES if status != "filtered"
)


def _values(statuses: tuple[str, ...]) -> str:
    return ", ".join(f"'{status}'" for status in statuses)


def upgrade() -> None:
    op.drop_constraint("processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PROCESSING_STATUSES)})",
    )


def downgrade() -> None:
    # Returned to the funnel rather than refused or deleted: a filtered row is
    # a kept article the gate declined, so the honest reverse of the gate is
    # the state the article had before it ran.
    op.execute("UPDATE signals SET processing_status = 'fetched' WHERE processing_status = 'filtered'")
    op.drop_constraint("processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PREVIOUS_PROCESSING_STATUSES)})",
    )
```

- [ ] **Step 5: Teach the web validator the status**

In `apps/web/src/lib/api-radar.ts`, add `"filtered",` to the
`PROCESSING_STATUSES` set after `"duplicate",`.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest apps/api/tests/test_migrations.py packages/backend/tests/test_schema_check.py -v
corepack pnpm test:web
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(schema): add the filtered processing status"
```

---

## Task 3: The keyword gate function

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/keyword_gate.py`
- Test: `packages/backend/tests/test_keyword_gate.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_keyword_gate.py`:

```python
from uuid import uuid4

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import FilterRule
from episignal_backend.ingestion.keyword_gate import classify_title

OUTBREAK = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_INCLUSION,
    pattern="outbreak",
    label="Context: outbreak",
)
MEASLES = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_INCLUSION,
    pattern="measles",
    label="Disease: Measles",
)
EXCLUSION = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_EXCLUSION,
    pattern=r"\bfever pitch\b",
    label="Fever pitch metaphor",
)


def test_a_disease_name_passes_the_gate() -> None:
    decision = classify_title("Measles spreads in Hanoi", (MEASLES, OUTBREAK))

    assert decision.passed is True
    assert decision.rule is MEASLES


def test_a_context_term_passes_the_gate() -> None:
    decision = classify_title("Health officials confirm outbreak", (MEASLES, OUTBREAK))

    assert decision.passed is True
    assert decision.rule is OUTBREAK


def test_a_clean_headline_is_filtered() -> None:
    decision = classify_title("City council approves new stadium", (MEASLES, OUTBREAK))

    assert decision.passed is False
    assert decision.rule is None


def test_matching_ignores_case_and_collapsed_whitespace() -> None:
    decision = classify_title("MEASLES\n  outbreak  declared", (MEASLES,))

    assert decision.passed is True


def test_an_empty_rule_set_passes_everything() -> None:
    # The gate can never be the reason a run stores nothing.
    decision = classify_title("City council approves new stadium", ())

    assert decision.passed is True
    assert decision.rule is None


def test_only_inclusion_rules_are_consulted() -> None:
    # Exclusion is discovery's job and runs before a signal exists at all.
    decision = classify_title("Fever pitch at the derby", (EXCLUSION,))

    assert decision.passed is True
    assert decision.rule is None


def test_a_blank_title_is_filtered() -> None:
    decision = classify_title("   ", (MEASLES,))

    assert decision.passed is False
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_keyword_gate.py -v
```

Expected: FAIL — `ModuleNotFoundError: episignal_backend.ingestion.keyword_gate`.

- [ ] **Step 3: Write the module**

Create `packages/backend/src/episignal_backend/ingestion/keyword_gate.py`:

```python
"""Stage 0, gate three: decide from the title whether an article is worth fetching.

Positive-only, and the mirror image of `filtering.py`. That gate rejects on an
explicit exclusion; this one keeps on explicit evidence and is deliberately
generous about what counts as evidence, because a filtered measles story costs
more than an extra extraction.

Matching is case-folded substring rather than a pattern: an inclusion keyword
is a word an epidemiologist would recognise, not an expression a reviewer has
to debug. An empty rule set passes everything, so the gate can never be the
reason a run stores nothing.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import FilterRule


@dataclass(frozen=True)
class GateDecision:
    """Pass with the rule that vouched for the title, or filter with nothing.

    A rejection carries no rule because it is the absence of every rule; there
    is nothing to attribute it to but the title, which is stored.
    """

    passed: bool
    rule: FilterRule | None = None


def classify_title(title: str, rules: Sequence[FilterRule]) -> GateDecision:
    inclusions = [rule for rule in rules if rule.rule_group is FilterRuleGroup.TITLE_INCLUSION]
    if not inclusions:
        # No configured evidence is not evidence of absence.
        return GateDecision(passed=True)

    needle = " ".join(title.split()).casefold()
    for rule in inclusions:
        if rule.pattern.casefold() in needle:
            return GateDecision(passed=True, rule=rule)

    return GateDecision(passed=False)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest packages/backend/tests/test_keyword_gate.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/keyword_gate.py packages/backend/tests/test_keyword_gate.py STATUS.md
git commit -m "feat(gate): classify a title against seeded inclusion keywords"
```

---

## Task 4: Repository seams for the gate

Three changes to `SqlAlchemyDiscoveryRepository`, and one bug fix that this
item's correctness depends on.

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/protocol.py:70-95`
- Modify: `packages/backend/src/episignal_backend/ingestion/repository.py:150-165,247-260`
- Test: `packages/backend/tests/test_discovery_repository.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/backend/tests/test_discovery_repository.py`, following the
session fixture that file already uses:

```python
def test_keyword_rules_union_the_seed_and_the_disease_vocabulary(session) -> None:
    repository = SqlAlchemyDiscoveryRepository(session)

    rules = repository.keyword_rules()
    patterns = {rule.pattern for rule in rules}

    assert "outbreak" in patterns  # a seeded title_inclusion row
    assert "cholera" in patterns  # a diseases.canonical_name, case-folded
    assert all(rule.rule_group is FilterRuleGroup.TITLE_INCLUSION for rule in rules)


def test_a_disease_synonym_is_also_a_keyword(session) -> None:
    repository = SqlAlchemyDiscoveryRepository(session)

    patterns = {rule.pattern for rule in repository.keyword_rules()}

    assert "evd" in patterns


def test_gated_signals_awaiting_retrieval_are_bodyless_and_fetched(session) -> None:
    repository = SqlAlchemyDiscoveryRepository(session)

    waiting = repository.gated_awaiting_retrieval(max_attempts=3, limit=10)

    assert {item.signal_id for item in waiting} == {DEFERRED_SIGNAL_ID}


def test_a_filtered_signal_is_never_selected_for_retrieval(session) -> None:
    repository = SqlAlchemyDiscoveryRepository(session)
    repository.record_filtered(DEFERRED_SIGNAL_ID)
    repository.commit()

    assert repository.gated_awaiting_retrieval(max_attempts=3, limit=10) == ()


def test_recording_filtered_preserves_the_row(session) -> None:
    repository = SqlAlchemyDiscoveryRepository(session)
    repository.record_filtered(DEFERRED_SIGNAL_ID)
    repository.commit()

    row = session.get(Signal, DEFERRED_SIGNAL_ID)
    assert row is not None
    assert row.processing_status is ProcessingStatus.FILTERED
    assert row.title
    assert row.url


def test_the_retry_pass_only_sees_needs_review_stubs(session) -> None:
    # A gate-passed signal is bodyless too. Without the status filter the
    # discover stage would fetch it before the gate ever ran, and would
    # re-fetch every filtered row forever.
    repository = SqlAlchemyDiscoveryRepository(session)

    stubs = repository.stubs_awaiting_retrieval(max_attempts=3, limit=10)

    assert DEFERRED_SIGNAL_ID not in {stub.signal_id for stub in stubs}
```

Add fixtures for `DEFERRED_SIGNAL_ID` — a GDELT signal at `fetched` with
`raw_text=None`, `retrieval_attempts=0`, and a source whose `domain` is set —
next to the fixtures the file already builds for stubs.

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_discovery_repository.py -v
```

Expected: FAIL — `AttributeError: keyword_rules`, and the retry test fails
because the deferred signal *is* returned.

- [ ] **Step 3: Add the protocol methods**

In `ingestion/protocol.py`, inside `DiscoveryRepository`:

```python
    def keyword_rules(self) -> Sequence[FilterRule]: ...

    def gated_awaiting_retrieval(
        self, *, max_attempts: int, limit: int
    ) -> Sequence[StubRetrieval]: ...

    def record_filtered(self, signal_id: UUID) -> None: ...
```

- [ ] **Step 4: Implement them**

In `ingestion/repository.py`, add to `SqlAlchemyDiscoveryRepository`:

```python
    def keyword_rules(self) -> Sequence[FilterRule]:
        """The gate's rule set: seeded context terms plus the reviewed vocabulary.

        The disease names are read rather than copied into the seed, so adding
        a disease widens the gate in the same commit that widens the
        vocabulary, and the two can never disagree.
        """
        seeded = self._session.execute(
            select(SignalFilterRule)
            .where(
                SignalFilterRule.active.is_(True),
                SignalFilterRule.rule_group == FilterRuleGroup.TITLE_INCLUSION,
            )
            .order_by(SignalFilterRule.label)
        ).scalars()
        rules = [
            FilterRule(
                id=row.id,
                rule_group=FilterRuleGroup.TITLE_INCLUSION,
                pattern=row.pattern,
                label=row.label,
            )
            for row in seeded
        ]

        diseases = self._session.execute(
            select(Disease.canonical_name, Disease.synonyms).order_by(Disease.canonical_name)
        ).all()
        for canonical_name, synonyms in diseases:
            for name in (canonical_name, *synonyms):
                collapsed = " ".join(name.split()).casefold()
                # Below four characters a substring match is an accident
                # waiting to happen, and the vocabulary holds a few acronyms.
                if len(collapsed) < 4:
                    continue
                rules.append(
                    FilterRule(
                        id=None,
                        rule_group=FilterRuleGroup.TITLE_INCLUSION,
                        pattern=collapsed,
                        label=f"Disease: {canonical_name}",
                    )
                )
        return tuple(rules)

    def gated_awaiting_retrieval(
        self, *, max_attempts: int, limit: int
    ) -> Sequence[StubRetrieval]:
        """Discoveries stored without a body, waiting for the gate.

        Distinct from `stubs_awaiting_retrieval`, which serves articles whose
        page already failed. These have never been asked for.
        """
        return self._retrievals(
            ProcessingStatus.FETCHED, max_attempts=max_attempts, limit=limit
        )

    def record_filtered(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.FILTERED)
        )
```

Then refactor the existing `stubs_awaiting_retrieval` body into a shared
`_retrievals(status, *, max_attempts, limit)` helper — the same query with the
status as a parameter — and make `stubs_awaiting_retrieval` call it with
`ProcessingStatus.NEEDS_REVIEW`:

```python
    def stubs_awaiting_retrieval(self, *, max_attempts: int, limit: int) -> Sequence[StubRetrieval]:
        return self._retrievals(
            ProcessingStatus.NEEDS_REVIEW, max_attempts=max_attempts, limit=limit
        )

    def _retrievals(
        self, status: ProcessingStatus, *, max_attempts: int, limit: int
    ) -> Sequence[StubRetrieval]:
        rows = self._session.execute(
            select(Signal, Source.domain, Source.country_code)
            .join(Source, Signal.source_id == Source.id)
            .where(
                # The status filter is load-bearing: without it this query
                # returns every bodyless signal, including the ones the gate
                # has not seen and the ones it filtered.
                Signal.processing_status == status,
                Signal.discovered_via == DiscoveryMethod.GDELT,
                Signal.raw_text.is_(None),
                Signal.retrieval_attempts < max_attempts,
                Source.domain.is_not(None),
            )
            .order_by(Signal.retrieval_attempts, Signal.first_seen_at)
            .limit(limit)
        ).all()
        # ... the existing StubRetrieval assembly, unchanged ...
```

Import `Disease`, `FilterRuleGroup`, and `SignalFilterRule` in that module if
they are not already imported.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest packages/backend/tests/test_discovery_repository.py packages/backend/tests/test_discovery_retry.py -v
```

Expected: PASS. If `test_discovery_retry.py` now fails, its fixture is
relying on the missing status filter — fix the fixture to store its stubs at
`needs_review`, which is what the retry pass has always meant.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(gate): read keyword rules and select bodyless signals"
```

---

## Task 5: Discovery stores without fetching

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/gdelt/connector.py`
- Modify: `packages/backend/src/episignal_backend/ingestion/protocol.py` (`DiscoveryConnector`)
- Modify: `packages/backend/src/episignal_backend/ingestion/discovery.py:130-165`
- Test: `packages/backend/tests/test_gdelt_connector.py`, `packages/backend/tests/test_discovery_pipeline.py`

- [ ] **Step 1: Write the failing tests**

In `packages/backend/tests/test_gdelt_connector.py`:

```python
def test_a_deferred_discovery_carries_no_body_and_no_fetch() -> None:
    fetcher = RecordingFetcher()
    connector = GdeltConnector(search=None, fetcher=fetcher, now=lambda: NOW)

    signal = connector.defer(ARTICLE, FIRST_SEEN)

    assert fetcher.calls == []
    assert signal.raw_text is None
    assert signal.processing_status is ProcessingStatus.FETCHED
    assert signal.title == ARTICLE.title
    assert signal.published_at is None
```

In `packages/backend/tests/test_discovery_pipeline.py`:

```python
def test_discovery_defers_every_retrieval() -> None:
    repository = FakeDiscoveryRepository(articles=(ARTICLE,))
    connector = CountingConnector()

    result = run_discovery(repository, connector, now=NOW)

    assert connector.retrieved == 0
    assert result.stored == 1
    assert result.needs_review == 0
    assert repository.added[0].processing_status is ProcessingStatus.FETCHED
    assert repository.added[0].raw_text is None
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_gdelt_connector.py packages/backend/tests/test_discovery_pipeline.py -v
```

Expected: FAIL — `AttributeError: defer`.

- [ ] **Step 3: Add `defer` to the connector**

In `ingestion/gdelt/connector.py`, after `retrieve`:

```python
    def defer(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        """A sighting stored before anyone has asked the publisher for the page.

        Distinct from `stub`, which records a page that was asked for and
        refused: this one is `fetched` and selectable by the retrieve stage,
        because nothing has gone wrong with it. The hash covers the title
        alone; `promote` recomputes it when the body arrives.
        """
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            raw_text=None,
            published_at=None,
            published_at_offset_minutes=None,
            retrieved_at=self._now(),
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash=content_hash(article.title, ""),
            publisher=self._publisher(article, None),
            query_rule_id=article.query_rule_id,
            processing_status=ProcessingStatus.FETCHED,
        )
```

Add `def defer(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal: ...`
to the `DiscoveryConnector` Protocol in `ingestion/protocol.py`.

- [ ] **Step 4: Stop `run_discovery` from retrieving**

In `ingestion/discovery.py`, replace the try/except around `connector.retrieve`
inside the `for article in selected:` loop with:

```python
    for article in selected:
        first_seen = repository.first_seen_at(article.canonical_url) or moment
        # Retrieval moved behind the keyword gate: a body is downloaded in the
        # retrieve stage, and only for an article whose title earned it.
        signal = connector.defer(article, first_seen)
```

Leave the storage block that follows exactly as it is. `needs_review` now
counts zero from this pass, which is honest: nothing was asked for and nothing
refused.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest packages/backend/tests/test_gdelt_connector.py packages/backend/tests/test_discovery_pipeline.py packages/backend/tests/test_discover_runner.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(discovery): store sightings without fetching the page"
```

---

## Task 6: The retrieval pass

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/retrieval.py`
- Test: `packages/backend/tests/test_retrieval.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_retrieval.py` with a fake repository
exposing `keyword_rules`, `gated_awaiting_retrieval`, `record_filtered`,
`promote`, `record_failed_attempt`, `commit`, `rollback`, and a fake connector
whose `retrieve` either returns a signal or raises `RetrievalFailed`:

```python
def test_a_gated_title_is_filtered_and_never_fetched() -> None:
    repository = FakeRetrievalRepository(waiting=(STADIUM,), rules=(OUTBREAK,))
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)

    assert result.filtered == 1
    assert result.retrieved == 0
    assert connector.retrieved == 0
    assert repository.filtered == [STADIUM.signal_id]


def test_a_passing_title_is_fetched_exactly_once() -> None:
    repository = FakeRetrievalRepository(waiting=(MEASLES_STORY,), rules=(OUTBREAK,))
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)

    assert result.retrieved == 1
    assert connector.retrieved == 1
    assert repository.promoted == [MEASLES_STORY.signal_id]


def test_an_unfetchable_page_records_a_failed_attempt() -> None:
    repository = FakeRetrievalRepository(waiting=(MEASLES_STORY,), rules=(OUTBREAK,))
    connector = CountingConnector(failing=True)

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)

    assert result.still_failing == 1
    assert repository.failed_attempts == [MEASLES_STORY.signal_id]
    assert repository.filtered == []


def test_a_redundant_promotion_is_counted_not_failed() -> None:
    repository = FakeRetrievalRepository(waiting=(MEASLES_STORY,), rules=(OUTBREAK,), promotable=False)
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)

    assert result.redundant == 1
    assert result.retrieved == 0


def test_a_storage_failure_rolls_back_and_keeps_going() -> None:
    repository = FakeRetrievalRepository(
        waiting=(MEASLES_STORY, SECOND_STORY), rules=(OUTBREAK,), failing_ids={MEASLES_STORY.signal_id}
    )
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)

    assert result.failed == 1
    assert result.retrieved == 1
    assert repository.rollbacks == 1


def test_no_signal_is_ever_deleted() -> None:
    repository = FakeRetrievalRepository(waiting=(STADIUM, MEASLES_STORY), rules=(OUTBREAK,))
    connector = CountingConnector()

    run_retrieval(repository, connector, max_attempts=3, batch_size=10)

    assert repository.deleted == []
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_retrieval.py -v
```

Expected: FAIL — `ModuleNotFoundError: episignal_backend.ingestion.retrieval`.

- [ ] **Step 3: Write the module**

Create `packages/backend/src/episignal_backend/ingestion/retrieval.py`:

```python
"""The gate-and-fetch pass: the only place a GDELT body is downloaded.

Discovery now stores a sighting with no body, so this pass is where a page is
paid for. It asks the keyword gate first, which is the whole point: a title
that shows no sign of a public health event never costs a page fetch.

Promotion, failure counting, and the retrieval_failed review path are the
existing ones, reached through the same repository the retry pass uses. This
module imports neither SQLAlchemy nor httpx.
"""

import logging
from dataclasses import dataclass

from episignal_backend.ingestion.keyword_gate import classify_title
from episignal_backend.ingestion.protocol import (
    DiscoveryConnector,
    DiscoveryRepository,
    RetrievalFailed,
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BATCH_SIZE = 200

logger = logging.getLogger("episignal_backend.ingestion.retrieval")


@dataclass(frozen=True)
class RetrievalResult:
    examined: int = 0
    filtered: int = 0
    retrieved: int = 0
    redundant: int = 0
    still_failing: int = 0
    failed: int = 0


def run_retrieval(
    repository: DiscoveryRepository,
    connector: DiscoveryConnector,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RetrievalResult:
    waiting = repository.gated_awaiting_retrieval(max_attempts=max_attempts, limit=batch_size)
    rules = repository.keyword_rules()
    if not rules:
        # Said out loud because an unseeded database and a deliberately empty
        # rule set look identical from the counts alone.
        logger.info("No active keyword rules; the gate is passing every title")

    filtered = 0
    retrieved = 0
    redundant = 0
    still_failing = 0
    failed = 0

    for item in waiting:
        decision = classify_title(item.article.title, rules)
        if not decision.passed:
            try:
                repository.record_filtered(item.signal_id)
                repository.commit()
            except Exception as error:
                repository.rollback()
                failed += 1
                logger.error(
                    "Could not record the filtering of %s (%s)",
                    item.article.canonical_url,
                    type(error).__name__,
                )
                continue
            filtered += 1
            continue

        try:
            signal = connector.retrieve(item.article, item.first_seen_at)
        except RetrievalFailed as reason:
            try:
                repository.record_failed_attempt(item.signal_id, max_attempts=max_attempts)
                repository.commit()
            except Exception as error:
                repository.rollback()
                failed += 1
                logger.error(
                    "Could not record a failed attempt for %s (%s)",
                    item.article.canonical_url,
                    type(error).__name__,
                )
            else:
                still_failing += 1
                logger.info("Retrieval of %s failed (%s)", item.article.canonical_url, reason)
            continue

        try:
            if repository.promote(item.signal_id, signal):
                retrieved += 1
            else:
                # Another row already carries this URL and hash. The bodyless
                # row is left exactly as it was: a spare row costs less than
                # deleting one on a guess.
                redundant += 1
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            logger.error(
                "Could not store the body of %s (%s)",
                item.article.canonical_url,
                type(error).__name__,
            )

    return RetrievalResult(
        examined=len(waiting),
        filtered=filtered,
        retrieved=retrieved,
        redundant=redundant,
        still_failing=still_failing,
        failed=failed,
    )
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest packages/backend/tests/test_retrieval.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(retrieve): gate a title before fetching its body"
```

---

## Task 7: The `retrieve` stage and its runner

**Files:**
- Create: `packages/backend/src/episignal_backend/retrieve_runner.py`
- Modify: `packages/backend/src/episignal_backend/schedule/documents.py:14-23`
- Modify: `packages/backend/src/episignal_backend/schedule/chains.py:11-19`
- Modify: `packages/backend/src/episignal_backend/schedule/stages.py`
- Modify: `package.json`
- Test: `packages/backend/tests/test_schedule_chains.py`, `test_schedule_stages.py`, `test_retrieve_runner.py`

- [ ] **Step 1: Write the failing tests**

Replace the chain assertion in `packages/backend/tests/test_schedule_chains.py`:

```python
def test_a_body_is_fetched_before_dedupe_needs_one() -> None:
    assert DAILY_CHAIN == (
        StageName.INGEST_WHO,
        StageName.INGEST_ECDC,
        StageName.DISCOVER,
        StageName.RETRIEVE,
        StageName.DEDUPE,
        StageName.PREGROUP,
        StageName.EXTRACT,
        StageName.GEOCODE,
        StageName.MATCH,
    )


def test_retrieval_precedes_dedupe() -> None:
    # Dedupe compares bodies and is the only writer of `normalized`. A chain
    # that dedupes before retrieval strands every signal at `fetched`.
    assert DAILY_CHAIN.index(StageName.RETRIEVE) < DAILY_CHAIN.index(StageName.DEDUPE)


def test_grouping_precedes_extraction() -> None:
    assert DAILY_CHAIN.index(StageName.PREGROUP) < DAILY_CHAIN.index(StageName.EXTRACT)
```

In `packages/backend/tests/test_schedule_stages.py`, assert the runner map
carries both new stages and that `build_stage_runners` returns one callable per
`StageName`.

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_schedule_chains.py packages/backend/tests/test_schedule_stages.py -v
```

Expected: FAIL — `AttributeError: RETRIEVE`.

- [ ] **Step 3: Add the stage names and the chain order**

In `schedule/documents.py`:

```python
class StageName(StrEnum):
    """One step of the pipeline. Never a rung of the model ladder: that is a tier."""

    INGEST_WHO = "ingest_who"
    INGEST_ECDC = "ingest_ecdc"
    DISCOVER = "discover"
    # The keyword gate and the page fetch. Between discovery and dedupe
    # because dedupe compares bodies and cannot see a signal without one.
    RETRIEVE = "retrieve"
    DEDUPE = "dedupe"
    # Story routing, before the pass that pays per story.
    PREGROUP = "pregroup"
    EXTRACT = "extract"
    GEOCODE = "geocode"
    MATCH = "match"
```

In `schedule/chains.py`, put `StageName.RETRIEVE` after `DISCOVER` and
`StageName.PREGROUP` after `DEDUPE`, and extend the module docstring: retrieval
precedes dedupe because dedupe compares bodies.

- [ ] **Step 4: Add the stage function**

In `schedule/stages.py`:

```python
def _retrieve() -> Mapping[str, int]:
    settings = get_settings()
    connector = GdeltConnector(
        search=GdeltDocClient(),
        fetcher=ArticleFetcher(
            delay_seconds=settings.gdelt_article_delay_seconds,
            user_agent=settings.gdelt_user_agent,
            timeout_seconds=settings.gdelt_article_timeout_seconds,
        ),
    )
    with session_scope() as session:
        result = run_retrieval(
            SqlAlchemyDiscoveryRepository(session),
            connector,
            max_attempts=settings.gdelt_max_retrieval_attempts,
            batch_size=settings.gdelt_max_articles_per_run,
        )
    return {
        "examined": result.examined,
        "filtered": result.filtered,
        "retrieved": result.retrieved,
        "redundant": result.redundant,
        "still_failing": result.still_failing,
        "failed": result.failed,
    }
```

Register it: `StageName.RETRIEVE: _retrieve,` in `build_stage_runners`.

- [ ] **Step 5: Write the runner**

Create `packages/backend/src/episignal_backend/retrieve_runner.py`, copying the
argument-parsing, error-handling, and counts-only printing shape of
`pregroup_runner.py`. It prints
`examined= filtered= retrieved= redundant= still_failing= failed=` and returns
`0`, or prints a type-name-only error to stderr and returns `1`.

Add to `package.json` scripts, after `dedupe:signals`:

```json
    "retrieve:signals": "uv run --package episignal-backend python -m episignal_backend.retrieve_runner",
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest packages/backend/tests/test_schedule_chains.py packages/backend/tests/test_schedule_stages.py packages/backend/tests/test_retrieve_runner.py packages/backend/tests/test_schedule_seams.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(schedule): run the retrieve stage before dedupe"
```

---

## Task 8: The `pregroup` stage

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/pregroup.py`
- Modify: `packages/backend/src/episignal_backend/ingestion/protocol.py`
- Modify: `packages/backend/src/episignal_backend/pregroup_runner.py:56-88`
- Modify: `packages/backend/src/episignal_backend/schedule/stages.py`
- Modify: `packages/backend/src/episignal_backend/config.py:139-142`
- Test: `packages/backend/tests/test_pregroup.py`, `test_pregroup_runner.py`, `test_config.py`

- [ ] **Step 1: Write the failing tests**

In `packages/backend/tests/test_pregroup.py`:

```python
def test_the_pass_closes_finished_groups_before_it_opens_new_ones() -> None:
    # Order matters: a representative that has left `normalized` frees its
    # members, and those members are candidates for this run's grouping.
    store = FakePreGroupStore(candidates=(FIRST, SECOND))

    result = run_pregroup(store, window_days=1, expiry_hours=72, batch_size=10, now=NOW)

    assert store.calls[0] == "resolve_and_expire"
    assert result.groups == 1
    assert result.deferred == 1


def test_a_disabled_pass_still_closes_open_groups() -> None:
    store = FakePreGroupStore(candidates=(FIRST, SECOND))

    result = run_pregroup(
        store, window_days=1, expiry_hours=72, batch_size=10, now=NOW, enabled=False
    )

    assert store.calls == ["resolve_and_expire"]
    assert result.groups == 0
    assert result.examined == 0
```

In `packages/backend/tests/test_config.py`:

```python
def test_pregrouping_is_on_by_default() -> None:
    assert Settings(database_url=VALID_URL).pregroup_enabled is True
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_pregroup.py packages/backend/tests/test_config.py -v
```

Expected: FAIL — `ImportError: run_pregroup`, and the config default is `False`.

- [ ] **Step 3: Extract the domain function**

Add a `PreGroupStore` Protocol to `ingestion/protocol.py` with
`candidates`, `write_groups`, `resolve_and_expire`, and `commit`. Then add to
`ingestion/pregroup.py`:

```python
@dataclass(frozen=True)
class PreGroupResult:
    examined: int = 0
    groups: int = 0
    deferred: int = 0
    resolved: int = 0
    expired: int = 0


def run_pregroup(
    store: PreGroupStore,
    *,
    window_days: int,
    expiry_hours: int,
    batch_size: int,
    now: datetime,
    enabled: bool = True,
) -> PreGroupResult:
    """Close finished groups, then route what is left.

    Close-out runs even when the stage is disabled: a flag flipped mid-flight
    must never leave a deferred signal unselectable forever, and "nothing is
    permanently unseen" is this stage's binding promise.
    """
    resolved, expired = store.resolve_and_expire(expiry_hours=expiry_hours, now=now)
    if not enabled:
        store.commit()
        return PreGroupResult(resolved=resolved, expired=expired)

    candidates = store.candidates(limit=batch_size)
    groups = group_signals(candidates, window_days=window_days)
    written = store.write_groups(groups, window_days=window_days, now=now)
    store.commit()

    return PreGroupResult(
        examined=len(candidates),
        groups=written,
        deferred=sum(len(group.deferred) for group in groups),
        resolved=resolved,
        expired=expired,
    )
```

Move `PreGroupResult` out of `pregroup_runner.py` and have the runner import it
and call `run_pregroup`, keeping its existing printing and exit codes.

- [ ] **Step 4: Add the stage and flip the default**

In `schedule/stages.py`:

```python
def _pregroup() -> Mapping[str, int]:
    settings = get_settings()
    with session_scope() as session:
        result = run_pregroup(
            SqlAlchemyPreGroupStore(session),
            window_days=settings.pregroup_window_days,
            expiry_hours=settings.pregroup_expiry_hours,
            batch_size=settings.pregroup_batch_size,
            now=datetime.now(UTC),
            enabled=settings.pregroup_enabled,
        )
    return {
        "examined": result.examined,
        "groups": result.groups,
        "deferred": result.deferred,
        "resolved": result.resolved,
        "expired": result.expired,
    }
```

Register `StageName.PREGROUP: _pregroup,`. In `config.py`:

```python
    # Pre-group stage. On by default since pipeline funnel v2: cluster
    # extraction selects open groups, so this flag is also the item's rollback
    # lever -- false means no groups, and every signal takes the per-article
    # path.
    pregroup_enabled: bool = True
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest packages/backend/tests/test_pregroup.py packages/backend/tests/test_pregroup_runner.py packages/backend/tests/test_config.py packages/backend/tests/test_schedule_stages.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(schedule): run pre-grouping as a chain stage"
```

---

## Task 9: Extraction selects without the relevance pass

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/repository.py:133-146,161-175`
- Modify: `packages/backend/src/episignal_backend/schedule/stages.py` (`_extract`)
- Test: `packages/backend/tests/test_ai_repository.py`, `test_schedule_stages.py`

- [ ] **Step 1: Write the failing tests**

In `packages/backend/tests/test_ai_repository.py`:

```python
def test_a_normalized_signal_is_extractable_without_a_relevance_pass(session) -> None:
    repository = SqlAlchemyAiRepository(session)

    pending = repository.awaiting_extraction(limit=10)

    assert NORMALIZED_SIGNAL_ID in {signal.id for signal in pending}


def test_a_signal_a_model_called_irrelevant_stays_out(session) -> None:
    repository = SqlAlchemyAiRepository(session)

    pending = repository.awaiting_extraction(limit=10)

    assert IRRELEVANT_SIGNAL_ID not in {signal.id for signal in pending}


def test_a_legacy_classified_signal_is_still_extractable(session) -> None:
    # Rows classified before the gate replaced the relevance pass must not be
    # stranded by the new selection.
    repository = SqlAlchemyAiRepository(session)

    assert CLASSIFIED_RELEVANT_ID in {s.id for s in repository.awaiting_extraction(limit=10)}


def test_a_deferred_member_of_an_open_group_is_not_extracted_alone(session) -> None:
    # The exclusion used to live on classification selection only. Extraction
    # is now the selection that has to honour it, or every member of every
    # group is extracted individually and the saving disappears.
    repository = SqlAlchemyAiRepository(session)

    assert DEFERRED_MEMBER_ID not in {s.id for s in repository.awaiting_extraction(limit=10)}
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_ai_repository.py -v
```

Expected: FAIL — normalized signals are not selected; the deferred member is.

- [ ] **Step 3: Widen and guard the selection**

In `ai/repository.py`:

```python
    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        stmt = (
            select(Signal)
            .where(
                # The keyword gate replaced the relevance pass, so `normalized`
                # is now the state that earns an extraction. `classified` stays
                # selectable so rows decided by the old pass are not stranded.
                Signal.processing_status.in_(
                    (ProcessingStatus.NORMALIZED, ProcessingStatus.CLASSIFIED)
                ),
                Signal.public_health_relevant.isnot(False),
                Signal.raw_text.is_not(None),
                # Moved here from `awaiting_classification` with the relevance
                # pass: this is the selection a deferred member must not reach.
                ~_deferred_by_open_group(),
            )
            .order_by(Signal.first_seen_at)
        )
        rows = self._scan_valid_signals(stmt, limit, "extraction")
        return tuple(
            ExtractableSignal(id=row.id, title=row.title, raw_text=row.raw_text or "")
            for row in rows
        )
```

- [ ] **Step 4: Unwire the relevance pass**

In `schedule/stages.py`, remove the `run_classification(...)` call from
`_extract` and its `classified`/`relevant`/`irrelevant` summary keys, keeping
the import removal clean for ruff. Add a comment where the call was:

```python
        # The relevance pass is gone from the chain: the keyword gate decides
        # relevance in the retrieve stage, for zero model requests. The pass
        # itself is kept in `ai/classify.py` so a rollback is one line here.
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest packages/backend/tests/test_ai_repository.py packages/backend/tests/test_schedule_stages.py packages/backend/tests/test_ai_classify.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(ai): extract from normalized signals and honour deferral"
```

---

## Task 10: Extraction schema version 3

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/schema.py:22-24,262-290`
- Modify: `packages/backend/src/episignal_backend/ai/repository.py:161-175`
- Test: `packages/backend/tests/test_ai_schema.py`, `test_ai_repository.py`

- [ ] **Step 1: Write the failing tests**

In `packages/backend/tests/test_ai_schema.py`:

```python
def test_a_grounded_count_defaults_to_the_only_member() -> None:
    count = GroundedCount(value=12, source_span="12 confirmed cases")

    assert count.source_index == 0


def test_a_grounded_count_can_cite_a_later_member() -> None:
    count = GroundedCount(value=12, source_span="12 confirmed cases", source_index=3)

    assert count.source_index == 3


def test_a_negative_source_index_is_refused() -> None:
    with pytest.raises(ValidationError):
        GroundedCount(value=12, source_span="12 confirmed cases", source_index=-1)


def test_the_stored_version_is_three() -> None:
    assert EXTRACTION_SCHEMA_VERSION == 3


def test_the_backfill_floor_stays_at_two() -> None:
    # A v2 row is a v3 row whose every claim cites member 0, so bumping the
    # version must not re-extract the corpus.
    assert BACKFILL_MIN_SCHEMA_VERSION == 2


def test_a_version_two_row_reads_back_with_index_zero() -> None:
    payload = StoredExtractionPayload.model_validate(V2_STORED_ROW)

    assert payload.epidemiology.deaths is not None
    assert payload.epidemiology.deaths.source_index == 0
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_ai_schema.py -v
```

Expected: FAIL — `source_index` is not a field; the version is 2.

- [ ] **Step 3: Add `source_index` and the constants**

In `ai/schema.py`:

```python
# Bumped when the shape of a stored extraction changes. Version 1 is every row
# written before the brief existed. Version 3 adds `source_index` to every
# grounded value, so one extraction can cite several articles of one story.
EXTRACTION_SCHEMA_VERSION = 3
EXTRACTION_VERSION_KEY = "extraction_schema_version"
# The backfill floor, deliberately not the version constant. A version 2 row is
# already a valid version 3 row -- every claim cites member 0, which is the
# only member it had -- so re-extracting the corpus would buy nothing and cost
# a run's whole budget.
BACKFILL_MIN_SCHEMA_VERSION = 2
```

Add to both `GroundedCount` and `GroundedFlag`:

```python
    # Which member of the story this claim was read from. Zero for a
    # single-article extraction, which is the one-member case of a cluster.
    source_index: int = Field(default=0, ge=0)
```

- [ ] **Step 4: Pin the backfill selection**

In `ai/repository.py`, `awaiting_backfill`, replace
`stored_version < EXTRACTION_SCHEMA_VERSION` with
`stored_version < BACKFILL_MIN_SCHEMA_VERSION` and import the new constant.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest packages/backend/tests/test_ai_schema.py packages/backend/tests/test_ai_repository.py packages/backend/tests/test_backfill_runner.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(ai): version 3 grounds every claim in a named member"
```

---

## Task 11: Grounding checked against the cited member

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/validate.py:139-175`
- Modify: `packages/backend/src/episignal_backend/ai/extract.py:88-92`
- Test: `packages/backend/tests/test_ai_validate.py`

- [ ] **Step 1: Write the failing tests**

In `packages/backend/tests/test_ai_validate.py`:

```python
FIRST_BODY = "Health officials confirmed 12 cases in Hanoi."
SECOND_BODY = "The ministry reported 3 deaths on Tuesday."


def test_each_claim_is_checked_against_the_member_it_cites() -> None:
    content = _answer(
        confirmed=("12 cases", 12, 0),
        deaths=("3 deaths", 3, 1),
    )

    extraction = validate_extraction(content, (FIRST_BODY, SECOND_BODY))

    assert extraction.epidemiology.deaths is not None
    assert extraction.epidemiology.deaths.source_index == 1


def test_a_span_from_the_wrong_member_is_ungrounded() -> None:
    # The span exists in the batch, but not in the article the claim names.
    content = _answer(deaths=("3 deaths", 3, 0))

    with pytest.raises(Rejected) as error:
        validate_extraction(content, (FIRST_BODY, SECOND_BODY))

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_a_source_index_past_the_last_member_is_ungrounded() -> None:
    content = _answer(deaths=("3 deaths", 3, 7))

    with pytest.raises(Rejected) as error:
        validate_extraction(content, (FIRST_BODY, SECOND_BODY))

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_the_single_article_case_is_the_one_member_case() -> None:
    content = _answer(confirmed=("12 cases", 12, 0))

    extraction = validate_extraction(content, (FIRST_BODY,))

    assert extraction.epidemiology.confirmed_cases is not None
```

`_answer` is a local helper building the minimal valid extraction JSON with the
five-slot brief, an English title, and confidence above the floor.

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_ai_validate.py -v
```

Expected: FAIL — `validate_extraction` takes a `str`, not a sequence.

- [ ] **Step 3: Ground against a sequence of bodies**

In `ai/validate.py`:

```python
def _check_span(span: str, bodies: Sequence[str], index: int, label: str) -> None:
    if not 0 <= index < len(bodies):
        # A claim that names an article nobody sent is ungrounded in the
        # strongest sense: there is no text it could ever be checked against.
        raise Rejected(RejectionReason.UNGROUNDED, f"{label} cites source_index {index}")
    if _flatten(span) not in bodies[index]:
        raise Rejected(RejectionReason.UNGROUNDED, label)


def check_grounding(extraction: Extraction, bodies: Sequence[str]) -> None:
    """Every claim against the one article it names, never against the batch.

    Checking a span against the concatenation would let one member's sentence
    vouch for another member's number, which is exactly the confusion batching
    invites and exactly what this system must never store.
    """
    flat_bodies = [_flatten(body) for body in bodies]

    for label, count in (
        ("suspected_cases", extraction.epidemiology.suspected_cases),
        ("confirmed_cases", extraction.epidemiology.confirmed_cases),
        ("total_cases", extraction.epidemiology.total_cases),
        ("deaths", extraction.epidemiology.deaths),
        ("new_cases", extraction.epidemiology.new_cases),
        ("new_deaths", extraction.epidemiology.new_deaths),
    ):
        if count is None:
            continue
        _check_span(count.source_span, flat_bodies, count.source_index, label)
        if str(count.value) not in count.source_span:
            raise Rejected(RejectionReason.UNGROUNDED, f"{label} not stated by its span")

    if extraction.transmission is not None:
        for label, flag in (
            ("local_transmission", extraction.transmission.local_transmission),
            ("imported", extraction.transmission.imported),
        ):
            if flag is not None:
                _check_span(flag.source_span, flat_bodies, flag.source_index, label)


def validate_extraction(
    content: str, bodies: Sequence[str], *, min_confidence: float = MIN_CONFIDENCE_DEFAULT
) -> Extraction:
    """Every check, in the design's order. The first failure raises."""
    extraction = parse_extraction(content)

    check_grounding(extraction, bodies)
    ...
```

The rest of `validate_extraction` is unchanged.

- [ ] **Step 4: Update the single-article call site**

In `ai/extract.py`:

```python
def _accept_builder(bodies: Sequence[str], min_confidence: float) -> Callable[[str], Extraction]:
    def _accept(content: str) -> Extraction:
        return validate_extraction(content, bodies, min_confidence=min_confidence)

    return _accept
```

and in `climb_one`: `accept=_accept_builder((signal.raw_text,), min_confidence)`.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest packages/backend/tests/test_ai_validate.py packages/backend/tests/test_ai_extract.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(ai): validate every span against the member it cites"
```

---

## Task 12: The cluster prompt

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/prompts.py`
- Test: `packages/backend/tests/test_ai_prompts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_cluster_prompt_labels_every_member() -> None:
    system, user = cluster_extraction_prompt(MEMBERS, max_characters=4000)

    assert "SOURCE 0" in user
    assert "SOURCE 1" in user
    assert "source_index" in system


def test_a_cluster_prompt_truncates_each_member_separately() -> None:
    _, user = cluster_extraction_prompt(LONG_MEMBERS, max_characters=100)

    for member in LONG_MEMBERS:
        assert member.raw_text not in user
    assert "SOURCE 1" in user


def test_a_cluster_prompt_carries_no_more_than_four_members() -> None:
    assert MAX_CLUSTER_MEMBERS == 4
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_ai_prompts.py -v
```

Expected: FAIL — `ImportError: cluster_extraction_prompt`.

- [ ] **Step 3: Write the prompt**

In `ai/prompts.py`:

```python
MAX_CLUSTER_MEMBERS = 4
CLUSTER_MEMBER_CHARACTERS = 4000

CLUSTER_EXTRACTION_RULES = """You read several news articles about the SAME event and return one set of epidemiological facts as JSON.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- The articles are numbered. Each begins with a line reading SOURCE n.
- Every count and every transmission flag must include source_index: the number
  of the single article you read it from, and source_span: a short phrase
  copied word for word from THAT article.
- Never combine two articles into one number. If they disagree, report the
  figure from the article you judge most authoritative and cite that article.
- Copy every source_span in its own article's language. Do not translate a span.
- Write title_english and every brief point in English. Translate rather than
  transliterate.
- Return exactly five brief points, one for each slot, in the order the schema
  lists them: what_where, counts, timing, spread, reporting.
- A slot no article addresses gets reported: false and one short line saying
  what is not reported. Never fill a slot from outside the articles.
- If no article states something, return null. Never infer, never estimate,
  never carry a number over from general knowledge.
- Do not state that an outbreak is confirmed. Report what the articles report.
- Do not include any person's name, telephone number, or address.

The object must match this JSON Schema exactly:
"""


def cluster_extraction_prompt(
    members: Sequence[ClusterMemberSignal], *, max_characters: int
) -> tuple[str, str]:
    """One request for one story, with every member kept separately addressable.

    The members are laid out with their index in the text rather than only in
    the schema, because the model has to cite an index it can see.
    """
    system = CLUSTER_EXTRACTION_RULES + json.dumps(extraction_json_schema(), sort_keys=True)
    blocks = [
        f"SOURCE {member.source_index}\nTITLE: {member.title}\n"
        f"ARTICLE:\n{truncate(member.raw_text, max_characters)}"
        for member in members
    ]
    return system, "\n\n---\n\n".join(blocks)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest packages/backend/tests/test_ai_prompts.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(ai): build one grounded prompt per story cluster"
```

---

## Task 13: Cluster documents and storage

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/documents.py`
- Modify: `packages/backend/src/episignal_backend/ai/protocol.py`
- Modify: `packages/backend/src/episignal_backend/ai/repository.py`
- Test: `packages/backend/tests/test_ai_documents.py`, `test_ai_repository.py`, `test_ai_protocol.py`

- [ ] **Step 1: Write the failing tests**

In `packages/backend/tests/test_ai_repository.py`:

```python
def test_an_open_group_is_offered_as_one_cluster(session) -> None:
    repository = SqlAlchemyAiRepository(session)

    clusters = repository.awaiting_cluster_extraction(limit=10)

    assert len(clusters) == 1
    assert clusters[0].representative_id == REPRESENTATIVE_ID
    assert clusters[0].members[0].source_index == 0
    assert clusters[0].members[0].id == REPRESENTATIVE_ID
    assert {m.id for m in clusters[0].members} == {REPRESENTATIVE_ID, DEFERRED_MEMBER_ID}


def test_a_cluster_never_carries_more_than_four_members(session) -> None:
    repository = SqlAlchemyAiRepository(session)

    for cluster in repository.awaiting_cluster_extraction(limit=10):
        assert len(cluster.members) <= MAX_CLUSTER_MEMBERS


def test_a_member_without_a_body_is_left_out_of_its_cluster(session) -> None:
    repository = SqlAlchemyAiRepository(session)

    members = repository.awaiting_cluster_extraction(limit=10)[0].members

    assert BODYLESS_MEMBER_ID not in {member.id for member in members}


def test_storing_a_cluster_marks_members_duplicate_of_the_representative(session) -> None:
    repository = SqlAlchemyAiRepository(session)

    repository.record_cluster_extraction(
        representative_id=REPRESENTATIVE_ID,
        member_ids=(DEFERRED_MEMBER_ID,),
        stored=STORED,
    )
    repository.commit()

    representative = session.get(Signal, REPRESENTATIVE_ID)
    member = session.get(Signal, DEFERRED_MEMBER_ID)
    assert representative.processing_status is ProcessingStatus.EXTRACTED
    assert representative.ai_extraction["extraction_schema_version"] == 3
    assert member.processing_status is ProcessingStatus.DUPLICATE
    assert member.duplicate_of_signal_id == REPRESENTATIVE_ID
    assert member.raw_text is not None  # nothing is deleted


def test_a_representative_is_never_marked_a_duplicate_of_itself(session) -> None:
    repository = SqlAlchemyAiRepository(session)

    repository.record_cluster_extraction(
        representative_id=REPRESENTATIVE_ID,
        member_ids=(REPRESENTATIVE_ID, DEFERRED_MEMBER_ID),
        stored=STORED,
    )
    repository.commit()

    representative = session.get(Signal, REPRESENTATIVE_ID)
    assert representative.duplicate_of_signal_id is None
    assert representative.processing_status is ProcessingStatus.EXTRACTED
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_ai_repository.py -v
```

Expected: FAIL — `AttributeError: awaiting_cluster_extraction`.

- [ ] **Step 3: Add the documents**

In `ai/documents.py`:

```python
class ClusterMemberSignal(BaseModel):
    """One article of a story, with the index its claims will cite."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    source_index: int = Field(ge=0)
    title: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)

    @field_validator("title", "raw_text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        return _require_text(value)


class ExtractableCluster(BaseModel):
    """One open story group, ready to be extracted once.

    The representative is always member zero, so the index a claim cites is
    stable between the prompt, the validator, and the stored payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    group_id: UUID
    representative_id: UUID
    members: tuple[ClusterMemberSignal, ...] = Field(min_length=1)

    @property
    def bodies(self) -> tuple[str, ...]:
        return tuple(member.raw_text for member in self.members)
```

- [ ] **Step 4: Add the protocol methods and implement them**

In `ai/protocol.py`, on `AiRepository`:

```python
    def awaiting_cluster_extraction(self, *, limit: int) -> Sequence[ExtractableCluster]: ...

    def record_cluster_extraction(
        self, *, representative_id: UUID, member_ids: Sequence[UUID], stored: StoredExtraction
    ) -> None: ...
```

In `ai/repository.py`:

```python
    def awaiting_cluster_extraction(self, *, limit: int) -> Sequence[ExtractableCluster]:
        """Open groups whose representative still owes an extraction.

        Members without a body are left out rather than sent as empty text: a
        member that cannot be quoted cannot ground a claim, and including it
        would only invite the model to cite an index that proves nothing.
        """
        group_ids = list(
            self._session.execute(
                select(StoryGroup.id)
                .join(
                    StoryGroupMember,
                    (StoryGroupMember.group_id == StoryGroup.id)
                    & (StoryGroupMember.role == StoryGroupRole.REPRESENTATIVE),
                )
                .join(Signal, StoryGroupMember.signal_id == Signal.id)
                .where(
                    StoryGroup.state == StoryGroupState.OPEN,
                    Signal.processing_status.in_(
                        (ProcessingStatus.NORMALIZED, ProcessingStatus.CLASSIFIED)
                    ),
                    Signal.public_health_relevant.isnot(False),
                    Signal.raw_text.is_not(None),
                )
                .order_by(StoryGroup.opened_at)
                .limit(limit)
            ).scalars()
        )

        clusters: list[ExtractableCluster] = []
        for group_id in group_ids:
            rows = self._session.execute(
                select(Signal, StoryGroupMember.role)
                .join(StoryGroupMember, StoryGroupMember.signal_id == Signal.id)
                .where(
                    StoryGroupMember.group_id == group_id,
                    Signal.raw_text.is_not(None),
                )
                .order_by(StoryGroupMember.role, Signal.first_seen_at)
            ).all()
            ordered = [row for row, role in rows if role is StoryGroupRole.REPRESENTATIVE]
            ordered += [row for row, role in rows if role is not StoryGroupRole.REPRESENTATIVE]
            ordered = [row for row in ordered if verify_content_hash(row.title, row.raw_text, row.content_hash)]
            if not ordered:
                continue
            members = tuple(
                ClusterMemberSignal(
                    id=row.id,
                    source_index=index,
                    title=row.title,
                    raw_text=row.raw_text or "",
                )
                for index, row in enumerate(ordered[:MAX_CLUSTER_MEMBERS])
            )
            clusters.append(
                ExtractableCluster(
                    group_id=group_id,
                    representative_id=members[0].id,
                    members=members,
                )
            )
        return tuple(clusters)

    def record_cluster_extraction(
        self, *, representative_id: UUID, member_ids: Sequence[UUID], stored: StoredExtraction
    ) -> None:
        self.record_extraction(representative_id, stored)
        for member_id in member_ids:
            if member_id == representative_id:
                # The representative carries the answer; it is nobody's copy.
                continue
            self._session.execute(
                update(Signal)
                .where(Signal.id == member_id)
                .values(
                    processing_status=ProcessingStatus.DUPLICATE,
                    duplicate_of_signal_id=representative_id,
                )
            )
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest packages/backend/tests/test_ai_repository.py packages/backend/tests/test_ai_documents.py packages/backend/tests/test_ai_protocol.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(ai): read a story group as one extractable cluster"
```

---

## Task 14: The cluster extraction pass

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/extract.py`
- Test: `packages/backend/tests/test_ai_cluster.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_cluster.py`, reusing the
`FakeRepository` / `ScriptedModel` fakes from `test_ai_classify.py` extended
with the two cluster methods:

```python
def test_one_accepted_cluster_costs_one_climb() -> None:
    repository = ClusterRepository(clusters=(TWO_MEMBER_CLUSTER,))
    model = ScriptedModel([ChatResponse(content=CLUSTER_ANSWER, latency_ms=10)])

    result = run_cluster_extraction(repository, model, guards=guards(), now=lambda: NOW)

    assert result.clusters == 1
    assert result.extracted == 1
    assert result.requests == 1
    assert result.fallbacks == 0


def test_an_accepted_cluster_marks_its_members_duplicate() -> None:
    repository = ClusterRepository(clusters=(TWO_MEMBER_CLUSTER,))
    model = ScriptedModel([ChatResponse(content=CLUSTER_ANSWER, latency_ms=10)])

    run_cluster_extraction(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.clustered == [(REPRESENTATIVE_ID, (MEMBER_ID,))]


def test_the_cost_row_records_the_cluster_size() -> None:
    repository = ClusterRepository(clusters=(TWO_MEMBER_CLUSTER,))
    model = ScriptedModel([ChatResponse(content=CLUSTER_ANSWER, latency_ms=10)])

    run_cluster_extraction(repository, model, guards=guards(), now=lambda: NOW)

    record = repository.requests[0]
    assert record.batch_size == 2
    assert record.signal_id == REPRESENTATIVE_ID
    assert record.purpose is AiPurpose.EXTRACTION


def test_a_rejected_cluster_falls_back_to_per_article_extraction() -> None:
    # One bad article must not poison the whole group's retry budget.
    repository = ClusterRepository(clusters=(TWO_MEMBER_CLUSTER,))
    model = ScriptedModel(
        [ChatResponse(content=UNGROUNDED_CLUSTER, latency_ms=10)] * LADDER_RUNGS
        + [ChatResponse(content=SINGLE_ANSWER, latency_ms=10)] * 2
    )

    result = run_cluster_extraction(repository, model, guards=guards(), now=lambda: NOW)

    assert result.fallbacks == 1
    assert result.extracted == 2
    assert repository.clustered == []


def test_a_span_from_the_wrong_member_is_rejected_end_to_end() -> None:
    repository = ClusterRepository(clusters=(TWO_MEMBER_CLUSTER,))
    model = ScriptedModel([ChatResponse(content=WRONG_MEMBER_SPAN, latency_ms=10)] * LADDER_RUNGS)

    result = run_cluster_extraction(repository, model, guards=guards(), now=lambda: NOW)

    assert result.extracted == 0 or result.fallbacks == 1
    assert repository.clustered == []


def test_the_budget_guard_stops_between_clusters() -> None:
    repository = ClusterRepository(clusters=(TWO_MEMBER_CLUSTER, SECOND_CLUSTER))
    model = ScriptedModel([ChatResponse(content=CLUSTER_ANSWER, latency_ms=10)])

    result = run_cluster_extraction(
        repository, model, guards=Guards(max_requests=1, max_cost_usd=Decimal("1")), now=lambda: NOW
    )

    assert result.stopped_early is True
    assert result.clusters == 1
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_ai_cluster.py -v
```

Expected: FAIL — `ImportError: run_cluster_extraction`.

- [ ] **Step 3: Write the pass**

In `ai/extract.py`, extend the result and add the pass:

```python
@dataclass(frozen=True)
class ClusterExtractionResult:
    clusters: int = 0
    extracted: int = 0
    reviewed: int = 0
    unavailable: int = 0
    fallbacks: int = 0
    storage_failed: int = 0
    requests: int = 0
    stopped_early: bool = False


def run_cluster_extraction(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    max_input_characters: int = CLUSTER_MEMBER_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    workers: int = DEFAULT_WORKERS,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ClusterExtractionResult:
    """Extract one answer per story, grounded in the member each claim names.

    Sequential over clusters, unlike the per-article pass: a cluster is already
    several articles' worth of tokens, and the budget guard has to be able to
    stop on a story boundary rather than mid-story.
    """
    ladder = Ladder.build(repository.models(), max_tier=max_tier, min_tier=EXTRACTION_MIN_TIER)
    budget = RunBudget(guards)
    clusters = repository.awaiting_cluster_extraction(limit=limit)

    extracted = 0
    reviewed = 0
    unavailable = 0
    fallbacks = 0
    storage_failed = 0
    requests = 0
    stopped_early = False

    for cluster in clusters:
        system, user = cluster_extraction_prompt(
            cluster.members, max_characters=max_input_characters
        )
        attempts: list[Attempt] = []
        result = climb(
            ladder=ladder,
            budget=budget,
            model=model,
            request_for=_request_builder(system, user),
            accept=_accept_builder(cluster.bodies, min_confidence),
            on_attempt=attempts.append,
        )
        requests += len(attempts)

        try:
            at = now()
            for attempt in attempts:
                repository.record_request(
                    cost_row(
                        attempt,
                        purpose=AiPurpose.EXTRACTION,
                        signal_id=cluster.representative_id,
                        batch_size=len(cluster.members),
                        at=at,
                    )
                )

            if result.outcome is ClimbOutcome.ACCEPTED and result.value is not None:
                disease_id = _resolve_disease(repository, model, ladder, result.value, cluster.representative_id, at)
                repository.record_cluster_extraction(
                    representative_id=cluster.representative_id,
                    member_ids=tuple(member.id for member in cluster.members),
                    stored=StoredExtraction(
                        extraction=result.value,
                        disease_id=disease_id,
                        model_id=attempts[-1].spec.model_id,
                        processed_at=at,
                    ),
                )
                extracted += 1
            repository.commit()
        except Exception as error:
            repository.rollback()
            storage_failed += 1
            logger.error(
                "Could not store the cluster extraction for group %s (%s)",
                cluster.group_id,
                type(error).__name__,
            )

        if result.outcome is ClimbOutcome.GUARD:
            stopped_early = True
            break

        if result.outcome is ClimbOutcome.REJECTED:
            # Per article, under the ordinary rules. One article the model
            # could not read across must not cost the whole story its budget.
            fallbacks += 1
            fallback = _run_pass(
                repository,
                model,
                tuple(
                    ExtractableSignal(id=m.id, title=m.title, raw_text=m.raw_text)
                    for m in cluster.members
                ),
                guards=guards,
                demote_on_rejection=True,
                max_tier=max_tier,
                min_confidence=min_confidence,
                workers=workers,
                now=now,
            )
            extracted += fallback.extracted
            reviewed += fallback.reviewed
            unavailable += fallback.unavailable
            storage_failed += fallback.storage_failed
            requests += fallback.requests
            if fallback.stopped_early:
                stopped_early = True
                break
        elif result.outcome is ClimbOutcome.UNAVAILABLE:
            unavailable += 1

    return ClusterExtractionResult(
        clusters=len(clusters),
        extracted=extracted,
        reviewed=reviewed,
        unavailable=unavailable,
        fallbacks=fallbacks,
        storage_failed=storage_failed,
        requests=requests,
        stopped_early=stopped_early,
    )
```

Extract the disease-resolution block currently inline in `_run_pass` into
`_resolve_disease(repository, model, ladder, extraction, signal_id, at)` and
call it from both passes, so the second-pass behaviour cannot diverge.

Note the `_run_pass` fallback re-uses `RunBudget` via `guards`; check that the
guard arithmetic in the fallback does not double-count against the cluster
budget, and if it does, thread the existing `budget` through instead of
`guards`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest packages/backend/tests/test_ai_cluster.py packages/backend/tests/test_ai_extract.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(ai): extract one story once, with a per-article fallback"
```

---

## Task 15: Wire cluster extraction into the extract stage

**Files:**
- Modify: `packages/backend/src/episignal_backend/schedule/stages.py` (`_extract`)
- Modify: `packages/backend/src/episignal_backend/extract_runner.py`
- Test: `packages/backend/tests/test_schedule_stages.py`, `test_extract_runner.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_extract_stage_clusters_before_it_extracts_singly() -> None:
    summary = _extract()

    assert set(summary) == {
        "clusters",
        "cluster_fallbacks",
        "extracted",
        "review",
        "unavailable",
        "requests",
    }


def test_the_extract_stage_makes_no_classification_request() -> None:
    # The keyword gate decides relevance now; a classification cost row in
    # this stage would mean the pass came back.
    _extract()

    assert [r.purpose for r in RECORDED if r.purpose is AiPurpose.CLASSIFICATION] == []
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_schedule_stages.py -v
```

Expected: FAIL — summary keys still carry `classified`.

- [ ] **Step 3: Wire the stage**

In `_extract`, after the model is routed:

```python
        clustered = run_cluster_extraction(
            repository,
            model,
            guards=guards,
            limit=settings.ai_signal_batch_limit,
            max_tier=settings.ai_max_tier,
            min_confidence=settings.ai_min_confidence,
            workers=settings.ai_extraction_workers,
        )
        # Whatever no group claimed: signals with no story, and the members
        # groups released when they resolved or expired.
        extracted = run_extraction(
            repository,
            model,
            guards=guards,
            limit=settings.ai_signal_batch_limit,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
            min_confidence=settings.ai_min_confidence,
            workers=settings.ai_extraction_workers,
        )
    return {
        "clusters": clustered.clusters,
        "cluster_fallbacks": clustered.fallbacks,
        "extracted": clustered.extracted + extracted.extracted,
        "review": clustered.reviewed + extracted.reviewed,
        "unavailable": clustered.unavailable + extracted.unavailable,
        "requests": clustered.requests + extracted.requests,
    }
```

Give `extract_runner` the same two passes and print
`clusters= fallbacks= extracted= review= unavailable= requests=`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest packages/backend/tests/test_schedule_stages.py packages/backend/tests/test_extract_runner.py packages/backend/tests/test_pipeline_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(schedule): cluster first, then extract the remainder"
```

---

## Task 16: Cluster spend is visible in the report

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/spend.py`
- Modify: `packages/backend/src/episignal_backend/spend_runner.py`
- Test: `packages/backend/tests/test_spend_report.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_summary_separates_clustered_from_single_requests(session) -> None:
    summary = trailing_spend(session, window_days=30, now=NOW)

    assert summary.clustered_requests == 2
    assert summary.clustered_signals == 5
    assert summary.requests == 4


def test_a_ledger_with_no_clusters_reports_zero(session) -> None:
    summary = trailing_spend(session, window_days=30, now=NOW)

    assert summary.clustered_requests == 0
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_spend_report.py -v
```

Expected: FAIL — `SpendSummary` has no `clustered_requests`.

- [ ] **Step 3: Add the two fields**

Add `clustered_requests: int` and `clustered_signals: int` to `SpendSummary`,
computed with one extra aggregate over `AiRequest.batch_size > 1` within the
same window. Print them in `spend_runner` as
`clustered=<requests> covering=<signals> signals`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest packages/backend/tests/test_spend_report.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(spend): report what clustering bought"
```

---

## Task 17: Documentation and the ADR

**Files:**
- Modify: `CONTEXT.md`
- Create: `docs/adr/2026-08-29-representative-carries-cluster-extraction.md`

- [ ] **Step 1: Update the funnel in `CONTEXT.md`**

Replace the pipeline diagram with the nine-stage chain, and add glossary
entries for **keyword gate**, **filtered**, **story group**, and **cluster
extraction**. Say plainly that a filtered signal is re-gated by setting it back
to `fetched`, and that inclusion keywords are matched as case-folded
substrings, so a keyword under four characters is a seeding error.

- [ ] **Step 2: Write the ADR**

`docs/adr/` is the location `docs/agents/domain.md` names for system-wide
decisions and does not exist yet — this is the first ADR, so create the
directory. Write
`docs/adr/2026-08-29-representative-carries-cluster-extraction.md`:

```markdown
# ADR — The representative signal carries a cluster's extraction

**Date:** 2026-08-29
**Status:** accepted
**Context item:** `O2` — Pipeline funnel v2

## Context

Four outlets reporting one outbreak produced four extraction requests and four
stored answers, of which the radar showed one, chosen arbitrarily. Extraction
is the most expensive thing this pipeline does, and it was being paid per
article rather than per story.

Pre-grouping already knows which signals are one story: `story_groups` holds a
deterministic grouping by rule group, country, and day window, with one
`representative` and the rest `deferred`.

## Decision

One extraction request carries up to four members of an open story group, each
labelled with a `source_index`. Every count and transmission flag the model
returns cites the index of the member it read the claim from, and the validator
checks each span against that member's text alone.

The accepted extraction is stored on the group's representative signal. The
other members are marked `duplicate` with `duplicate_of_signal_id` pointing at
the representative — the same terminal state a syndicated copy reaches today.

## Consequences

- Geocoding, event matching, and the radar read model change not at all: they
  already see one signal per story, and they already ignore duplicates.
- Per-member provenance is stored (each claim carries its `source_index`) but
  is not displayable: the read model has no notion of a group.
- A rejected cluster call falls back to per-article extraction for that group's
  members, so one unreadable article cannot cost the story its budget.
- Deferred retrieval, introduced by the same item, has no feature flag; its
  rollback is a revert. Cluster extraction does have one:
  `pregroup_enabled=false` writes no groups, so nothing is selectable for
  cluster extraction and every signal takes the per-article path.

## Revisit when

Per-member provenance becomes a product need — a reader wants to see which of
four outlets reported which number. At that point the extraction moves out of
`signals.ai_extraction` into its own table keyed by group, and the radar read
model grows a notion of a story. That change was deliberately deferred here
because it ripples through the read model for no efficiency gain.
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: record the funnel and the cluster extraction decision"
```

---

## Task 18: Live proof

**Files:**
- No source changes. Output is captured for Task 19.

- [ ] **Step 1: Migrate and seed the live database**

```bash
corepack pnpm db:migrate && corepack pnpm db:seed && corepack pnpm db:check
```

- [ ] **Step 2: Record the pre-run state**

Capture, read-only: counts of signals by `processing_status`, the current
`spend:report` output, and the number of open review cases. This is the
before-picture the report compares against.

- [ ] **Step 3: Run the chain once**

```bash
corepack pnpm pipeline:run
```

- [ ] **Step 4: Capture the funnel**

Record every stage's counts from the run, plus:

- `filtered` count from the retrieve stage, and the same count as a share of examined;
- `retrieved` count, versus the number of articles discovered;
- `clusters` and `cluster_fallbacks` from the extract stage;
- total extraction requests and cost, against the recorded baseline of
  **105 requests / 43 extracted signals / ~$0.30 lifetime ledger**;
- at least one accepted cluster extraction, with its stored payload showing
  distinct `source_index` values across its claims. Quote the payload.

If the live run produces no multi-member group, say so plainly and report the
single-member numbers; do not manufacture a group. The fallback path is proven
by the Task 14 test in that case, and the report must say which proof is which.

- [ ] **Step 5: Confirm the backfill queue did not grow**

Count rows selectable by `awaiting_backfill` before and after. The two numbers
must match: the schema version moved to 3, and the floor stayed at 2.

- [ ] **Step 6: Do not resolve live review cases**

No review case is resolved for demonstration. Synthetic fixtures stay clearly
labelled and are never presented as live proof.

- [ ] **Step 7: Commit nothing**

This task produces evidence, not code. Tick the ledger item in Task 19's commit.

---

## Task 19: Review, verify, report

**Files:**
- Create: `docs/reports/2026-08-29-pipeline-funnel-v2-report.md`
- Modify: `STATUS.md` (Verified baseline)

- [ ] **Step 1: Load `code-review` and act on it**

Review the whole branch diff against the spec. Fix what the review finds, in
its own commits.

- [ ] **Step 2: Load `verify-and-stop` and run the real command**

```bash
corepack pnpm verify
```

Record the actual output: exit code, Python test count, web test count, lint,
types, contracts, build. Never a paraphrase, never a remembered number.

- [ ] **Step 3: Write the report**

`docs/reports/2026-08-29-pipeline-funnel-v2-report.md` carries: the verification
output verbatim, the Task 18 funnel numbers against the 105/43/$0.30 baseline,
the accepted cluster payload with its per-member `source_index` values, which
proofs are live and which are tests, and every deviation from this plan with
its reason.

- [ ] **Step 4: Update the worker-owned baseline**

Update the **Verified baseline** table in `STATUS.md` with the commit the
verification actually ran at, the new migration revision `20260829_0016`, and
the new trailing spend.

- [ ] **Step 5: Commit and hand back**

```bash
git add -A
git commit -m "docs: report pipeline funnel v2 completion"
```

Hand back to the planner. **Do not** set the roadmap item to `verified`, and do
not begin another roadmap item.

---

## Scope guard

Do not: build or wire embedding similarity; touch `D2b`; change the geocode
ladder or its rungs; change event matching weights or thresholds; change the
radar read model to display cluster membership; delete or re-enrich existing v2
extraction rows; wire the Gemini batch API; add a new configuration flag;
delete `ai/classify.py`; or resolve live review cases.

Existing v2 rows stay readable through `StoredExtractionPayload` and are never
migrated in place.

**If the plan turns out to be wrong, stop and report.** Correcting a plan is
planner work, per `docs/agents/workflow.md`. Improvising a different design is
the one failure this contract does not tolerate.

---

## Self-review notes

Checked against the spec, section by section:

- D1 → Tasks 1, 3, 4 (rule group, gate function, rule union with the vocabulary).
- D2 → Task 2 (status, CHECK constraint, web validator).
- D3 → Tasks 4, 5, 6, 7 (status filter fix, `defer`, the pass, the stage).
- D4 → Tasks 8, 9 (the stage, the flag default, the deferral exclusion).
- D5 → Tasks 10, 11, 12, 13, 14 (version, grounding, prompt, storage, pass).
- D6 → Tasks 7, 9 (chain shape; classification kept but unwired).
- Acceptance → Tasks 18, 19.

Type consistency: `classify_title` and `GateDecision` are used identically in
Tasks 3, 6; `ClusterMemberSignal.source_index` is the same integer the prompt
prints in Task 12, the validator indexes in Task 11, and the schema defaults in
Task 10; `run_retrieval` returns the same six counts the stage maps in Task 7
and the runner prints.

Known risk the worker must watch: Task 14's fallback re-enters `_run_pass` with
`guards` rather than the cluster pass's live `RunBudget`. The step says so and
tells the worker to thread the budget through if the double-count is real.
