import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from episignal_backend.ai.documents import ExtractableSignal, StoredExtraction, Verdict
from episignal_backend.ai.extract import ExtractionResult, run_backfill, run_extraction
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.db.types import AiOutcome, AiPurpose
from test_ai_classify import (
    NOW,
    FakeRepository,
    ScriptedModel,
    guards,
)

FIXTURES = Path(__file__).parent / "fixtures"
BODY = (FIXTURES / "ai_outbreak_body.txt").read_text(encoding="utf-8")
FRENCH = (FIXTURES / "ai_multilingual_body.txt").read_text(encoding="utf-8")
GOOD = (FIXTURES / "ai_extraction_response.json").read_text(encoding="utf-8")
UNGROUNDED = (FIXTURES / "ai_ungrounded_response.json").read_text(encoding="utf-8")
FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")
SECOND = UUID("b3f1c2d4-0000-4000-8000-000000000002")
CHOLERA = UUID("b3f1c2d4-0000-4000-8000-0000000000ff")

FRENCH_ANSWER = json.dumps(
    {
        "signal_type": "outbreak_report",
        "source_language": "fr",
        "title_english": "Cholera outbreak spreads in Luanda province, Angola",
        "brief": [
            {"slot": "what_where", "text": "Cholera in Luanda province, Angola.", "reported": True},
            {"slot": "counts", "text": "327 confirmed cases and 14 deaths.", "reported": True},
            {"slot": "timing", "text": "Figures are as of 25 August 2026.", "reported": True},
            {"slot": "spread", "text": "All cases were acquired locally.", "reported": True},
            {"slot": "reporting", "text": "Reported by Angola's health ministry.", "reported": True},
        ],
        "disease": {"name": "Cholera", "confidence": 0.96},
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {
            "confirmed_cases": {"value": 327, "source_span": "327 cas confirmés"},
            "deaths": {"value": 14, "source_span": "14 personnes sont mortes"},
        },
        "dates": {"data_as_of": "2026-08-25"},
        "transmission": {
            "local_transmission": {
                "value": True,
                "source_span": "tous les cas avaient été contractés localement",
            }
        },
        "confidence": 0.93,
    }
)


class ExtractRepository(FakeRepository):
    def __init__(
        self,
        pending: Sequence[ExtractableSignal],
        diseases: dict[str, UUID] | None = None,
    ) -> None:
        super().__init__(())
        self._pending = tuple(pending)
        self._diseases = diseases or {}
        self.stored: dict[UUID, StoredExtraction] = {}

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return self._pending[:limit]

    def resolve_disease(self, name: str) -> UUID | None:
        return self._diseases.get(name.lower())

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        raise AssertionError("the extraction pass must not write a verdict")

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        self.stored[signal_id] = stored


class BackfillRepository(ExtractRepository):
    def __init__(self, stale: Sequence[ExtractableSignal]) -> None:
        super().__init__(())
        self._stale = tuple(stale)
        self.asked_for_backfill = False

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        raise AssertionError("the backfill must not select new work")

    def awaiting_backfill(self, *, limit: int) -> Sequence[ExtractableSignal]:
        self.asked_for_backfill = True
        return self._stale[:limit]

    def mark_needs_review(self, signal_id: UUID) -> None:
        raise AssertionError("a rejected re-extraction must leave the row where it is")


class CommitFailingBackfillRepository(BackfillRepository):
    def __init__(self, stale: Sequence[ExtractableSignal]) -> None:
        super().__init__(stale)
        self.rollbacks = 0

    def commit(self) -> None:
        raise RuntimeError("database unavailable")

    def rollback(self) -> None:
        self.rollbacks += 1


def english(identifier: UUID = FIRST) -> ExtractableSignal:
    return ExtractableSignal(id=identifier, title="Cholera cases rise", raw_text=BODY)


def french() -> ExtractableSignal:
    return ExtractableSignal(id=SECOND, title="Le choléra progresse", raw_text=FRENCH)


def run(repository: ExtractRepository, model: ScriptedModel) -> ExtractionResult:
    return run_extraction(repository, model, guards=guards(), limit=100, now=lambda: NOW)


def test_a_grounded_extraction_is_stored_with_its_model_and_time() -> None:
    repository = ExtractRepository((english(),))

    result = run(repository, ScriptedModel([GOOD]))

    assert result == ExtractionResult(
        examined=1, extracted=1, reviewed=0, unavailable=0, requests=1, stopped_early=False
    )
    assert repository.stored[FIRST].processed_at == NOW
    assert repository.stored[FIRST].model_id == "vendor1/model:free"
    assert (
        repository.stored[FIRST].extraction.brief[-1].text
        == "Reported by Angola's health ministry."
    )


def test_the_resolved_disease_is_attached_when_the_vocabulary_knows_it() -> None:
    repository = ExtractRepository((english(),), diseases={"cholera": CHOLERA})

    run(repository, ScriptedModel([GOOD]))

    assert repository.stored[FIRST].disease_id == CHOLERA


def test_an_unknown_disease_leaves_the_link_empty_rather_than_guessing() -> None:
    repository = ExtractRepository((english(),), diseases={})

    run(repository, ScriptedModel([GOOD]))

    assert repository.stored[FIRST].disease_id is None


def test_an_ungrounded_answer_escalates_and_the_signal_is_not_written() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([UNGROUNDED, GOOD])

    run(repository, model)

    assert len(model.asked) == 2
    assert repository.stored[FIRST].extraction.epidemiology.deaths is not None
    assert repository.stored[FIRST].extraction.epidemiology.deaths.value == 14


def test_an_ungrounded_answer_at_every_tier_sends_one_signal_for_review() -> None:
    repository = ExtractRepository((english(),))

    result = run(repository, ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED]))

    assert repository.reviewed == [FIRST]
    assert repository.stored == {}
    assert result.reviewed == 1


def test_a_french_article_with_a_grounded_answer_makes_exactly_one_request() -> None:
    repository = ExtractRepository((french(),))
    model = ScriptedModel([FRENCH_ANSWER])

    result = run(repository, model)

    assert len(model.asked) == 1
    assert result.extracted == 1
    assert (
        repository.stored[SECOND].extraction.brief[-1].text
        == "Reported by Angola's health ministry."
    )


def test_an_unreachable_provider_leaves_the_signal_selectable() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel(
        [ModelUnavailable("429"), ModelUnavailable("429"), ModelUnavailable("429")]
    )

    run(repository, model)

    assert repository.reviewed == []
    assert repository.stored == {}


def test_each_extraction_cost_row_names_its_single_signal() -> None:
    repository = ExtractRepository((english(),))

    run(repository, ScriptedModel([UNGROUNDED, GOOD]))

    assert [record.outcome for record in repository.requests] == [
        AiOutcome.REJECTED,
        AiOutcome.ACCEPTED,
    ]
    assert all(record.purpose is AiPurpose.EXTRACTION for record in repository.requests)
    assert all(record.signal_id == FIRST for record in repository.requests)
    assert all(record.batch_size == 1 for record in repository.requests)


def test_one_failing_signal_does_not_stop_the_rest_of_the_queue() -> None:
    repository = ExtractRepository((english(), french()))
    model = ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED, FRENCH_ANSWER])

    result = run(repository, model)

    assert result.extracted == 1
    assert result.reviewed == 1


def test_each_signal_is_committed_on_its_own() -> None:
    repository = ExtractRepository((english(), french()))

    run(repository, ScriptedModel([GOOD, FRENCH_ANSWER]))

    assert repository.commits == 2


def test_the_backfill_re_extracts_a_stale_signal() -> None:
    signal = ExtractableSignal(id=FIRST, title="Cholera in Luanda", raw_text=BODY)
    repository = BackfillRepository([signal])
    model = ScriptedModel([GOOD])

    result = run_backfill(repository, model, guards=guards(), now=lambda: NOW)

    assert result.examined == 1
    assert result.extracted == 1
    assert FIRST in repository.stored


def test_the_backfill_asks_for_stale_work_and_never_for_new_work() -> None:
    repository = BackfillRepository([])
    model = ScriptedModel([])

    run_backfill(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.asked_for_backfill is True


def test_a_rejected_re_extraction_leaves_the_row_exactly_where_it_was() -> None:
    signal = ExtractableSignal(id=FIRST, title="Cholera in Luanda", raw_text=BODY)
    repository = BackfillRepository([signal])
    model = ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED])

    result = run_backfill(repository, model, guards=guards(), now=lambda: NOW)

    assert result.extracted == 0
    assert FIRST not in repository.stored


def test_a_rejected_first_extraction_still_goes_to_review() -> None:
    signal = ExtractableSignal(id=SECOND, title="Cholera in Luanda", raw_text=BODY)
    repository = ExtractRepository([signal])
    model = ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED])

    result = run_extraction(repository, model, guards=guards(), now=lambda: NOW)

    assert result.reviewed == 1


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

