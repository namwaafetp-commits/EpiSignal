# C2 Completion Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four findings from the planner's C2 completion review so backfill failures are reported honestly, language codes satisfy the approved contract, test evidence preserves provenance, and live verification proves a coherent extraction.

**Architecture:** Keep the existing C2 design and schema version. Extend the shared extraction result with one storage-failure count, update counters only after a successful commit, and let the backfill runner translate all failure counts into a non-zero process exit. Validate `source_language` against the stable ISO 639-1 vocabulary, correct unsupported statements in fixtures, then replace the incomplete live evidence without changing production data by hand.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, SQLAlchemy 2, PostgreSQL JSONB, Ruff, mypy strict, pnpm.

**Spec:** [docs/superpowers/specs/2026-08-28-english-brief-design.md](../specs/2026-08-28-english-brief-design.md)

**Original plan:** [docs/superpowers/plans/2026-08-28-english-brief.md](2026-08-28-english-brief.md)

---

## Review findings this plan closes

1. `backfill_runner.main()` returns exit code 0 even when a re-extraction is rejected or the provider is unavailable.
2. `_run_pass()` increments outcome counters before `repository.commit()`, so a rolled-back write can still be reported as successful.
3. `source_language` accepts any two ASCII letters rather than only ISO 639-1 codes.
4. Good-answer fixtures add unsupported reporting claims, and the completion report uses an internally inconsistent database row and omits the second backfill proof.

Do not redesign the brief, add a migration, change the schema version, wire backfill into the scheduler, or modify discovery, dedupe, geocoding, clustering, or UI code.

## File structure

**Modified:**

| File | Responsibility after this correction |
| --- | --- |
| `packages/backend/src/episignal_backend/ai/extract.py` | Counts a signal outcome only after its transaction commits and exposes storage failures separately. |
| `packages/backend/src/episignal_backend/backfill_runner.py` | Prints backfill-specific counts and exits non-zero for every rejected, unavailable, or storage-failed signal. |
| `packages/backend/src/episignal_backend/ai/schema.py` | Accepts only real ISO 639-1 `source_language` values or null. |
| `packages/backend/tests/test_ai_extract.py` | Proves rollback cannot be reported as extraction success and keeps multilingual fixture attribution source-backed. |
| `packages/backend/tests/test_backfill_runner.py` | Proves each failure category produces exit code 1 without leaking payloads. |
| `packages/backend/tests/test_ai_schema.py` | Proves syntactically plausible non-ISO language codes are rejected. |
| `packages/backend/tests/test_ai_validate.py` | Uses source-backed reporting text in accepted payloads. |
| `packages/backend/tests/test_ai_repository.py` | Uses the same source-backed brief in persistence expectations. |
| `packages/backend/tests/fixtures/ai_extraction_response.json` | Represents a fully grounded accepted answer. |
| `packages/backend/tests/fixtures/ai_ungrounded_response.json` | Remains rejected only for its intentionally ungrounded span. |
| `docs/reports/2026-08-28-subproject-c2-report.md` | Records corrected gate and coherent live evidence. |
| `STATUS.md` | Worker ticks the correction ledger and refreshes the verified baseline from its own run. |

No file is created by the worker. Do not edit `ROADMAP.md` or `HANDOFF.md`; those remain planner-owned.

---

### Task 1: Count only committed extraction outcomes

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/extract.py:43-161`
- Test: `packages/backend/tests/test_ai_extract.py`

- [ ] **Step 1: Write the failing storage-failure regression test**

Add this fake below `BackfillRepository` in `packages/backend/tests/test_ai_extract.py`:

```python
class CommitFailingBackfillRepository(BackfillRepository):
    def __init__(self, stale: Sequence[ExtractableSignal]) -> None:
        super().__init__(stale)
        self.rollbacks = 0

    def commit(self) -> None:
        raise RuntimeError("database unavailable")

    def rollback(self) -> None:
        self.rollbacks += 1
```

Add this test beside the existing backfill tests:

```python
def test_a_rolled_back_backfill_is_not_reported_as_extracted() -> None:
    signal = ExtractableSignal(id=FIRST, title="Cholera in Luanda", raw_text=BODY)
    repository = CommitFailingBackfillRepository([signal])

    result = run_backfill(
        repository,
        ScriptedModel([GOOD]),
        guards=guards(),
        now=lambda: NOW,
    )

    assert result.extracted == 0
    assert result.storage_failed == 1
    assert repository.rollbacks == 1
```

- [ ] **Step 2: Run the test and verify the expected failure**

Run:

```powershell
uv run pytest packages/backend/tests/test_ai_extract.py::test_a_rolled_back_backfill_is_not_reported_as_extracted -v
```

Expected: FAIL because `ExtractionResult` has no `storage_failed` field and currently reports `extracted == 1` before the commit fails.

- [ ] **Step 3: Add the storage-failure count**

In `ExtractionResult`, add the field without changing existing field meanings:

```python
@dataclass(frozen=True)
class ExtractionResult:
    examined: int = 0
    extracted: int = 0
    reviewed: int = 0
    unavailable: int = 0
    storage_failed: int = 0
    requests: int = 0
    stopped_early: bool = False
```

Initialize the counter beside the other counters in `_run_pass`:

```python
    extracted = 0
    reviewed = 0
    unavailable = 0
    storage_failed = 0
    requests = 0
    stopped_early = False
```

- [ ] **Step 4: Move outcome accounting after the commit**

Replace the current `try`/`except` body in `_run_pass` with this structure. Repository writes still happen in the same transaction; only counters move:

```python
        try:
            at = now()
            for attempt in attempts:
                repository.record_request(
                    cost_row(
                        attempt,
                        purpose=AiPurpose.EXTRACTION,
                        signal_id=signal.id,
                        batch_size=1,
                        at=at,
                    )
                )

            if result.outcome is ClimbOutcome.ACCEPTED and result.value is not None:
                disease_id = (
                    repository.resolve_disease(result.value.disease.name)
                    if result.value.disease
                    else None
                )
                repository.record_extraction(
                    signal.id,
                    StoredExtraction(
                        extraction=result.value,
                        disease_id=disease_id,
                        model_id=attempts[-1].spec.model_id,
                        processed_at=at,
                    ),
                )
            elif result.outcome is ClimbOutcome.REJECTED and demote_on_rejection:
                repository.mark_needs_review(signal.id)

            repository.commit()
        except Exception as error:
            repository.rollback()
            storage_failed += 1
            logger.error(
                "Could not store extraction for signal %s (%s)",
                signal.id,
                type(error).__name__,
            )
        else:
            if result.outcome is ClimbOutcome.ACCEPTED and result.value is not None:
                extracted += 1
            elif result.outcome is ClimbOutcome.REJECTED:
                reviewed += 1
            else:
                unavailable += 1
```

Add the new field to the returned result:

```python
    return ExtractionResult(
        examined=len(pending),
        extracted=extracted,
        reviewed=reviewed,
        unavailable=unavailable,
        storage_failed=storage_failed,
        requests=requests,
        stopped_early=stopped_early,
    )
```

Do not change the existing guard break below the transaction block.

- [ ] **Step 5: Run focused and neighboring tests**

Run:

```powershell
uv run pytest packages/backend/tests/test_ai_extract.py packages/backend/tests/test_extract_runner.py packages/backend/tests/test_pipeline_runner.py -v
```

Expected: PASS. Existing `ExtractionResult(...)` constructions remain valid because `storage_failed` defaults to zero.

- [ ] **Step 6: Tick correction task 1 and commit**

Tick correction task 1 in `STATUS.md`, then run:

```powershell
git add packages/backend/src/episignal_backend/ai/extract.py packages/backend/tests/test_ai_extract.py STATUS.md
git commit -m "fix: report rolled-back extraction writes"
```

---

### Task 2: Make the backfill command fail honestly

**Files:**
- Modify: `packages/backend/src/episignal_backend/backfill_runner.py:83-90`
- Test: `packages/backend/tests/test_backfill_runner.py`

- [ ] **Step 1: Generalize the result fixture**

Replace `_extraction_result` in `packages/backend/tests/test_backfill_runner.py` with:

```python
def _extraction_result(
    *,
    extracted: int = 5,
    reviewed: int = 0,
    unavailable: int = 0,
    storage_failed: int = 0,
) -> ExtractionResult:
    return ExtractionResult(
        examined=5,
        extracted=extracted,
        reviewed=reviewed,
        unavailable=unavailable,
        storage_failed=storage_failed,
        requests=5,
    )
```

- [ ] **Step 2: Write failing exit-code tests**

Add these tests after `test_a_successful_run_prints_counts_only`:

```python
@pytest.mark.parametrize(
    "result",
    [
        _extraction_result(extracted=4, reviewed=1),
        _extraction_result(extracted=4, unavailable=1),
        _extraction_result(extracted=4, storage_failed=1),
    ],
)
def test_any_failed_signal_makes_the_command_fail(
    result: ExtractionResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "episignal_backend.backfill_runner._run",
        lambda arguments: result,
    )

    assert main([]) == 1
```

Change the success test's output assertions to the intended backfill vocabulary:

```python
    output = capsys.readouterr().out
    assert "examined=5" in output
    assert "re_extracted=5" in output
    assert "rejected=0" in output
    assert "storage_failed=0" in output
```

- [ ] **Step 3: Run the tests and verify the expected failures**

Run:

```powershell
uv run pytest packages/backend/tests/test_backfill_runner.py -v
```

Expected: three parameter cases FAIL because `main()` returns 0, and the success-output test FAILS because the runner prints `extracted` and `review`.

- [ ] **Step 4: Implement the command result contract**

Replace the final print and return in `backfill_runner.main` with:

```python
    print(
        f"examined={result.examined} re_extracted={result.extracted} "
        f"rejected={result.reviewed} unavailable={result.unavailable} "
        f"storage_failed={result.storage_failed} requests={result.requests} "
        f"stopped_early={result.stopped_early}"
    )
    return (
        0
        if result.reviewed == 0
        and result.unavailable == 0
        and result.storage_failed == 0
        else 1
    )
```

Do not print model errors, prompts, keys, article text, or exception payloads.

- [ ] **Step 5: Run focused tests and type checking**

Run:

```powershell
uv run pytest packages/backend/tests/test_backfill_runner.py packages/backend/tests/test_ai_extract.py -v
uv run mypy apps/api/src packages/backend/src
```

Expected: all tests PASS and mypy reports `Success`.

- [ ] **Step 6: Tick correction task 2 and commit**

```powershell
git add packages/backend/src/episignal_backend/backfill_runner.py packages/backend/tests/test_backfill_runner.py STATUS.md
git commit -m "fix: fail backfill when any signal fails"
```

---

### Task 3: Enforce the ISO 639-1 vocabulary

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/schema.py:10-187`
- Test: `packages/backend/tests/test_ai_schema.py`

- [ ] **Step 1: Write the failing vocabulary test**

Add beside the existing source-language tests:

```python
def test_a_two_letter_code_outside_iso_639_1_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(source_language="zz"))


def test_a_known_language_code_is_normalized_to_lowercase() -> None:
    extraction = Extraction.model_validate(minimal(source_language="FR"))

    assert extraction.source_language == "fr"
```

- [ ] **Step 2: Run the tests and verify one fails**

Run:

```powershell
uv run pytest packages/backend/tests/test_ai_schema.py -v -k "language_code or source_language"
```

Expected: `zz` test FAILS because the current regex accepts it; `FR` test PASSES.

- [ ] **Step 3: Replace syntax-only validation with the stable vocabulary**

Remove `import re`. Add this constant beside the schema constants:

```python
ISO_639_1_CODES: frozenset[str] = frozenset(
    """
    aa ab ae af ak am an ar as av ay az
    ba be bg bh bi bm bn bo br bs
    ca ce ch co cr cs cu cv cy
    da de dv dz
    ee el en eo es et eu
    fa ff fi fj fo fr fy
    ga gd gl gn gu gv
    ha he hi ho hr ht hu hy hz
    ia id ie ig ii ik io is it iu
    ja jv
    ka kg ki kj kk kl km kn ko kr ks ku kv kw ky
    la lb lg li ln lo lt lu lv
    mg mh mi mk ml mn mr ms mt my
    na nb nd ne ng nl nn no nr nv ny
    oc oj om or os
    pa pi pl ps pt
    qu
    rm rn ro ru rw
    sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw
    ta te tg th ti tk tl tn to tr ts tt tw ty
    ug uk ur uz
    ve vi vo
    wa wo
    xh
    yi yo
    za zh zu
    """.split()
)
```

Replace `language_is_a_code` with:

```python
    @field_validator("source_language")
    @classmethod
    def language_is_a_code(cls, value: str | None) -> str | None:
        # Null means the model was unsure, which is recorded rather than guessed.
        if value is None:
            return None
        code = value.strip().lower()
        if code not in ISO_639_1_CODES:
            raise ValueError("source_language must be an ISO 639-1 two-letter code or null")
        return code
```

- [ ] **Step 4: Run schema, validation, and type tests**

Run:

```powershell
uv run pytest packages/backend/tests/test_ai_schema.py packages/backend/tests/test_ai_validate.py -v
uv run mypy apps/api/src packages/backend/src
```

Expected: PASS and mypy `Success`.

- [ ] **Step 5: Tick correction task 3 and commit**

```powershell
git add packages/backend/src/episignal_backend/ai/schema.py packages/backend/tests/test_ai_schema.py STATUS.md
git commit -m "fix: validate extraction language codes"
```

---

### Task 4: Make accepted fixtures source-backed

**Files:**
- Modify: `packages/backend/tests/fixtures/ai_extraction_response.json`
- Modify: `packages/backend/tests/fixtures/ai_ungrounded_response.json`
- Modify: `packages/backend/tests/test_ai_extract.py`
- Modify: `packages/backend/tests/test_ai_schema.py`
- Modify: `packages/backend/tests/test_ai_validate.py`
- Modify: `packages/backend/tests/test_ai_repository.py`

- [ ] **Step 1: Add assertions that reproduce the fixture defects**

In `test_a_grounded_extraction_is_stored_with_its_model_and_time`, add:

```python
    assert (
        repository.stored[FIRST].extraction.brief[-1].text
        == "Reported by Angola's health ministry."
    )
```

In `test_a_french_article_with_a_grounded_answer_makes_exactly_one_request`, add:

```python
    assert (
        repository.stored[SECOND].extraction.brief[-1].text
        == "Reported by Angola's health ministry."
    )
```

- [ ] **Step 2: Run both tests and verify they fail for the unsupported text**

Run:

```powershell
uv run pytest packages/backend/tests/test_ai_extract.py::test_a_grounded_extraction_is_stored_with_its_model_and_time packages/backend/tests/test_ai_extract.py::test_a_french_article_with_a_grounded_answer_makes_exactly_one_request -v
```

Expected: first test shows the unsupported `not independently verified` suffix; second shows the false `local media` attribution.

- [ ] **Step 3: Correct every accepted C2 fixture**

Replace these two unsupported forms everywhere in the files listed above:

```text
Reported by Angola's health ministry; not independently verified.
Reported by the health ministry; not independently verified.
```

and:

```text
Reported by local media.
```

with this source-backed English line:

```text
Reported by Angola's health ministry.
```

Update the expected newline-joined summary in `test_ai_repository.py` to use the same final line.

The intentionally ungrounded JSON fixture must remain identical to the grounded fixture except for its pre-existing intentionally bad `source_span`; do not introduce another rejection reason.

- [ ] **Step 4: Prove unsupported fixture phrases are gone**

Run:

```powershell
rg -n "not independently verified|Reported by local media" packages/backend/tests
```

Expected: no output and exit code 1 because no match exists.

- [ ] **Step 5: Run the extraction and validation suites**

Run:

```powershell
uv run pytest packages/backend/tests/test_ai_schema.py packages/backend/tests/test_ai_validate.py packages/backend/tests/test_ai_extract.py packages/backend/tests/test_ai_repository.py -v
```

Expected: PASS.

- [ ] **Step 6: Tick correction task 4 and commit**

```powershell
git add packages/backend/tests/fixtures/ai_extraction_response.json packages/backend/tests/fixtures/ai_ungrounded_response.json packages/backend/tests/test_ai_extract.py packages/backend/tests/test_ai_schema.py packages/backend/tests/test_ai_validate.py packages/backend/tests/test_ai_repository.py STATUS.md
git commit -m "test: keep brief fixtures source-backed"
```

---

### Task 5: Replace incomplete completion evidence

This task is the only correction task that may touch the live database or spend model requests. Do not manually edit, delete, downgrade, or fabricate a signal to manufacture backfill evidence.

**Files:**
- Modify: `docs/reports/2026-08-28-subproject-c2-report.md`
- Modify: `STATUS.md` — correction ticks and verified baseline only

- [ ] **Step 1: Run the complete verification gate at the code commit**

Run:

```powershell
git status --short
git rev-parse HEAD
corepack pnpm verify
```

Expected: clean tree before the run and exit code 0. Preserve the untruncated output and the exact commit SHA for the report.

- [ ] **Step 2: Confirm the live database without changing it**

Run:

```powershell
corepack pnpm db:check
```

Expected: `database=up postgis=up`.

- [ ] **Step 3: Run the complete extraction command, not classification alone**

Run:

```powershell
corepack pnpm extract:signals -- --limit 5
```

Expected: counts-only output with `extracted=` above zero. If it reports zero extracted signals, stop and report the live-proof blocker; do not substitute the known inconsistent row `852aa204-846d-4aa6-a256-82c187fdeaef`.

- [ ] **Step 4: Inspect the newest candidates for coherent provenance**

Run this read-only query:

```powershell
@'
from sqlalchemy import text
from episignal_backend.db.session import session_scope

with session_scope() as session:
    rows = session.execute(text("""
        SELECT id, title, canonical_url,
               ai_extraction->>'title_english' AS title_english,
               ai_extraction->'disease'->>'name' AS disease,
               ai_extraction->>'extraction_schema_version' AS version,
               jsonb_array_length(ai_extraction->'brief') AS brief_length,
               left(raw_text, 300) AS raw_prefix,
               left(summary, 300) AS brief_prefix
        FROM signals
        WHERE ai_extraction ? 'brief'
        ORDER BY ai_processed_at DESC
        LIMIT 5
    """)).all()
    for row in rows:
        print(row)
'@ | uv run --package episignal-backend python -
```

Select evidence only when publisher title, URL, raw-text prefix, English title, disease, and brief describe the same signal. Expected version is `2` and brief length is `5`. If none are coherent, stop and report an upstream source-integrity finding rather than claiming C2 acceptance.

- [ ] **Step 5: Prove backfill idempotence honestly**

Run:

```powershell
corepack pnpm extract:backfill -- --limit 10
```

Expected now: `examined=0`, because the earlier accepted run already upgraded the only stale candidate. The completion report must retain the original chronological `examined=1` output and add this actual zero-work rerun. Explain that the rerun happened during correction review; do not claim the two commands were immediate.

- [ ] **Step 6: Rewrite the completion report around valid evidence**

Update `docs/reports/2026-08-28-subproject-c2-report.md` so it contains:

- the correction commit range and exact gate commit;
- full untruncated `corepack pnpm verify` output and exit code;
- `db:check` output;
- the full-stage `extract:signals` output from step 3;
- one coherent row from step 4, including signal ID, publisher title, English title, schema version, brief length, disease, raw-text prefix, and brief prefix;
- the original `examined=1` backfill line and the new `examined=0` rerun, labelled with their actual chronology;
- explicit removal of the inconsistent measles-title/cholera-body row from acceptance evidence;
- corrected backfill exit semantics, storage-failure accounting, ISO language validation, and fixture provenance tests;
- any remaining warning or risk, without calling the item verified.

Remove the current conclusion that C2 is verified. End with: `Ready for planner re-review; the worker has not changed ROADMAP.md or HANDOFF.md.`

- [ ] **Step 7: Refresh only worker-owned status fields**

In `STATUS.md`:

- tick correction task 5;
- update the **Verified baseline** counts and commit from step 1;
- update live extraction/backfill facts with the actual commands and results.

Do not change **Position**, **Next action**, **Blockers**, `ROADMAP.md`, or `HANDOFF.md`.

- [ ] **Step 8: Check the report and tracking diff**

Run:

```powershell
git diff --check
git diff -- docs/reports/2026-08-28-subproject-c2-report.md STATUS.md
```

Expected: `git diff --check` exits 0. Confirm no secret, API key, full article body, or patient-level information appears in the report.

- [ ] **Step 9: Commit and hand back**

```powershell
git add docs/reports/2026-08-28-subproject-c2-report.md STATUS.md
git commit -m "docs: correct sub-project C2 completion evidence"
git status --short
```

Expected: commit succeeds and final tree is clean. Hand back the gate SHA, test counts, live command outputs, coherent signal ID, and any remaining risk. Do not mark C2 `verified`.

---

## Worker stop conditions

Stop and report instead of improvising when any of these occurs:

- the focused regression fails for a reason other than the expected old behavior;
- fixing a task requires a migration or a change outside the files listed for that task;
- full extraction produces no new extraction suitable for coherent live proof;
- newest stored rows show title/body/URL disagreement like the rejected evidence row;
- any live command would require manually corrupting or downgrading production data;
- `corepack pnpm verify` fails.

## Final proof set

The planner will re-review only after all five correction tasks are ticked, the report is committed, the tree is clean, and the report contains the actual gate output. Passing tests alone is insufficient: backfill exit behavior and coherent live provenance are acceptance evidence.
