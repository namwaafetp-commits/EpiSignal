import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from episignal_backend.ai.classify_disease import DiseaseCandidate
from episignal_backend.ai.documents import (
    ChatResponse,
    ClusterMemberSignal,
    ExtractableCluster,
    ExtractableSignal,
    StoredExtraction,
    TokenUsage,
    Verdict,
)
from episignal_backend.ai.extract import ExtractionResult, run_backfill, run_extraction
from episignal_backend.ai.ladder import Guards
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

CANDIDATES = (
    DiseaseCandidate(
        slug="cholera",
        canonical_name="Cholera",
        synonyms=("Vibrio cholerae infection",),
    ),
    DiseaseCandidate(
        slug="ebola-virus-disease",
        canonical_name="Ebola virus disease",
        synonyms=("EVD", "Ebola haemorrhagic fever"),
    ),
)

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
            {
                "slot": "reporting",
                "text": "Reported by Angola's health ministry.",
                "reported": True,
            },
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
        candidates: Sequence[DiseaseCandidate] = (),
        clusters: Sequence[ExtractableCluster] = (),
    ) -> None:
        super().__init__(())
        self._pending = tuple(pending)
        self._diseases = diseases or {}
        self._candidates = tuple(candidates)
        self._clusters = tuple(clusters)
        self.stored: dict[UUID, StoredExtraction] = {}
        self.recorded_clusters: list[tuple[UUID, tuple[UUID, ...], StoredExtraction]] = []

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return self._pending[:limit]

    def awaiting_cluster_extraction(self, *, limit: int) -> Sequence[ExtractableCluster]:
        return self._clusters[:limit]

    def record_cluster_extraction(
        self, *, representative_id: UUID, member_ids: Sequence[UUID], stored: StoredExtraction
    ) -> None:
        self.recorded_clusters.append((representative_id, tuple(member_ids), stored))
        self.stored[representative_id] = stored

    def resolve_disease(self, name: str) -> UUID | None:
        return self._diseases.get(name.lower())

    def disease_candidates(self) -> Sequence[DiseaseCandidate]:
        return self._candidates

    def resolve_disease_slug(self, slug: str) -> UUID | None:
        return CHOLERA if slug == "cholera" else None

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

    def record_extraction_failure(self, signal_id: UUID) -> None:
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
    # The extraction ladder floors at tier 2, so the first ask is the T2 rung.
    assert repository.stored[FIRST].model_id == "vendor2/model:free"
    assert (
        repository.stored[FIRST].extraction.brief[-1].text
        == "Reported by Angola's health ministry."
    )


def test_extraction_requests_carry_schema_and_low_temperature() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([GOOD])

    run(repository, model)

    assert len(model.requests) == 1
    assert model.requests[0].response_schema is not None
    assert model.requests[0].schema_name == "extraction_response"
    assert model.requests[0].temperature == 0.0


def _answer_without_location() -> str:
    payload = json.loads(GOOD)
    payload["locations"] = []
    return json.dumps(payload)


def _answer_with_identity(disease: str, country: str, place: str) -> str:
    payload = json.loads(GOOD)
    payload["disease"]["name"] = disease
    payload["locations"] = [{"role": "primary", "country": country, "place_name": place}]
    return json.dumps(payload)


def test_missing_identity_gets_one_top_rung_identity_retry() -> None:
    long_body = BODY + "\n" + ("Additional context. " * 500)
    signal = ExtractableSignal(id=FIRST, title="Cholera cases rise", raw_text=long_body)
    model = ScriptedModel([_answer_without_location(), GOOD])

    result = run_extraction(
        ExtractRepository((signal,)),
        model,
        guards=guards(),
        max_input_characters=12000,
        now=lambda: NOW,
    )

    assert result.extracted == 1
    assert result.requests == 2
    assert result.expanded_retries == 1
    assert len(model.requests) == 2
    assert len(model.requests[1].user) > len(model.requests[0].user)
    assert model.asked == ["vendor2/model:free", "vendor3/model:free"]
    assert "IDENTITY REPAIR:" in model.requests[1].user
    assert "TITLE: Cholera cases rise" in model.requests[1].user
    assert BODY in model.requests[1].user
    assert model.requests[0].response_schema == model.requests[1].response_schema


def test_complete_initial_extraction_does_not_expand() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([GOOD])

    result = run(repository, model)

    assert result.requests == 1
    assert result.expanded_retries == 0


def test_short_article_gets_identity_retry() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([_answer_without_location(), GOOD])

    result = run(repository, model)

    assert result.extracted == 1
    assert result.requests == 2
    assert result.expanded_retries == 1
    assert model.asked == ["vendor2/model:free", "vendor3/model:free"]


def test_request_guard_stops_before_identity_retry_and_keeps_initial_answer() -> None:
    long_body = BODY + "\n" + ("Additional context. " * 500)
    signal = ExtractableSignal(id=FIRST, title="Cholera cases rise", raw_text=long_body)
    repository = ExtractRepository((signal,))
    model = ScriptedModel([_answer_without_location()])

    result = run_extraction(
        repository,
        model,
        guards=Guards(max_requests=1, max_cost_usd=Decimal("1")),
        max_input_characters=12000,
        now=lambda: NOW,
    )

    assert result.extracted == 1
    assert result.requests == 1
    assert result.expanded_retries == 1
    assert result.stopped_early is True


def test_failed_identity_retry_preserves_initial_extraction() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([_answer_without_location(), ModelUnavailable("429")])

    result = run(repository, model)

    assert result.extracted == 1
    assert result.requests == 2
    assert repository.stored[FIRST].extraction.locations == ()
    assert model.asked == ["vendor2/model:free", "vendor3/model:free"]


def test_rejected_identity_retry_preserves_initial_extraction() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([_answer_without_location(), UNGROUNDED])

    result = run(repository, model)

    assert result.extracted == 1
    assert result.requests == 2
    assert repository.stored[FIRST].extraction.locations == ()
    assert model.asked == ["vendor2/model:free", "vendor3/model:free"]


def test_identity_retry_happens_only_once() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([_answer_without_location(), _answer_without_location(), GOOD])

    result = run(repository, model)

    assert result.extracted == 1
    assert result.requests == 2
    assert model.asked == ["vendor2/model:free", "vendor3/model:free"]
    assert len(model.script) == 1
    assert repository.stored[FIRST].extraction.locations == ()


@pytest.mark.parametrize(
    ("disease", "country", "place"),
    (
        ("Ebola", "CD", "North Kivu"),
        ("Nipah virus", "IN", "Kerala"),
        ("measles", "US", "Pennsylvania"),
        ("MERS-CoV", "SA", "Riyadh"),
        ("malaria", "DE", "Frankfurt"),
        ("H5N1", "AU", "South Australia"),
    ),
)
def test_identity_retry_keeps_explicit_disease_and_country(
    disease: str, country: str, place: str
) -> None:
    signal = ExtractableSignal(
        id=FIRST,
        title=f"{disease} reported in {place}",
        raw_text=BODY,
    )
    repository = ExtractRepository((signal,))
    model = ScriptedModel(
        [_answer_without_location(), _answer_with_identity(disease, country, place)]
    )

    run_extraction(repository, model, guards=guards(), limit=100, now=lambda: NOW)

    stored = repository.stored[FIRST].extraction
    assert stored.disease is not None
    assert stored.disease.name == disease
    assert stored.locations[0].country == country


def test_a_genuinely_non_event_article_does_not_gain_identity() -> None:
    signal = ExtractableSignal(
        id=FIRST,
        title="Back-to-school health checklist",
        raw_text="No disease outbreak is reported in this checklist.",
    )
    payload = json.loads(GOOD)
    payload["title_english"] = "Health checklist"
    payload["brief"] = [
        {"slot": slot, "text": "Not reported.", "reported": False}
        for slot in ("what_where", "counts", "timing", "spread", "reporting")
    ]
    payload["disease"] = None
    payload["locations"] = []
    payload["epidemiology"] = {}
    payload["dates"] = {}
    payload["transmission"] = None
    payload["response_actions"] = []
    payload["driver_or_barrier_evidence"] = []
    answer = json.dumps(payload)
    repository = ExtractRepository((signal,))

    run_extraction(
        repository,
        ScriptedModel([answer, answer]),
        guards=guards(),
        limit=100,
        now=lambda: NOW,
    )

    stored = repository.stored[FIRST].extraction
    assert stored.disease is None
    assert stored.locations == ()


def test_the_resolved_disease_is_attached_when_the_vocabulary_knows_it() -> None:
    repository = ExtractRepository((english(),), diseases={"cholera": CHOLERA})

    run(repository, ScriptedModel([GOOD]))

    assert repository.stored[FIRST].disease_id == CHOLERA


def test_an_unknown_disease_leaves_the_link_empty_rather_than_guessing() -> None:
    repository = ExtractRepository((english(),), diseases={})

    run(repository, ScriptedModel([GOOD]))

    assert repository.stored[FIRST].disease_id is None


def test_a_vocabulary_miss_leaves_the_disease_unlinked() -> None:
    repository = ExtractRepository((english(),), candidates=CANDIDATES)
    model = ScriptedModel([GOOD])

    run(repository, model)

    assert repository.stored[FIRST].disease_id is None
    assert model.asked == ["vendor2/model:free"]
    assert all(record.purpose is AiPurpose.EXTRACTION for record in repository.requests)


def test_a_second_pass_null_keeps_the_disease_unlinked() -> None:
    repository = ExtractRepository((english(),), candidates=CANDIDATES)
    model = ScriptedModel([GOOD, json.dumps({"slug": None})])

    run(repository, model)

    assert repository.stored[FIRST].disease_id is None
    assert repository.rejected == []


def test_a_failing_second_pass_still_stores_the_extraction() -> None:
    repository = ExtractRepository((english(),), candidates=CANDIDATES)
    model = ScriptedModel([GOOD, RuntimeError("provider exploded")])

    run(repository, model)

    assert FIRST in repository.stored
    assert repository.stored[FIRST].disease_id is None


def test_a_vocabulary_hit_never_asks_the_classifier() -> None:
    repository = ExtractRepository(
        (english(),), diseases={"cholera": CHOLERA}, candidates=CANDIDATES
    )
    model = ScriptedModel([GOOD])

    run(repository, model)

    assert len(model.asked) == 1
    assert repository.stored[FIRST].disease_id == CHOLERA
    assert all(record.purpose is AiPurpose.EXTRACTION for record in repository.requests)


def test_an_ungrounded_answer_escalates_and_the_signal_is_not_written() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([UNGROUNDED, GOOD])

    run(repository, model)

    assert len(model.asked) == 2
    assert repository.stored[FIRST].extraction.epidemiology.deaths is not None
    assert repository.stored[FIRST].extraction.epidemiology.deaths.value == 14


def test_an_ungrounded_answer_at_every_tier_reports_one_signal_rejected() -> None:
    repository = ExtractRepository((english(),))

    result = run(repository, ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED]))

    assert repository.rejected == [FIRST]
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

    assert repository.rejected == []
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


def test_one_rejected_signal_does_not_stop_the_rest_of_the_queue() -> None:
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


def test_a_rejected_first_extraction_is_reported_as_reviewed() -> None:
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


class BarrierModel:
    """Answers only when `parties` climbs are in flight at once.

    A sequential pass would deadlock on the barrier and time out, so a green
    run is the proof that the climbs really ran concurrently.
    """

    def __init__(self, parties: int, answer: str) -> None:
        import threading

        self._barrier = threading.Barrier(parties)
        self._answer = answer
        self.completed = 0
        self._lock = threading.Lock()

    def complete(self, request):
        self._barrier.wait(timeout=10)
        response = ChatResponse(
            content=self._answer,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=10),
            http_status=200,
            latency_ms=1,
        )
        with self._lock:
            self.completed += 1
        return response


def test_extraction_climbs_run_concurrently_and_land_in_order() -> None:
    signals = tuple(
        ExtractableSignal(
            id=UUID("b3f1c2d4-0000-4000-8000-00000000000" + str(index)),
            title=f"Cholera cases rise {index}",
            raw_text=BODY,
        )
        for index in range(1, 5)
    )
    repository = ExtractRepository(signals)
    model = BarrierModel(parties=4, answer=GOOD)

    result = run_extraction(
        repository,
        model,
        guards=guards(),
        limit=100,
        workers=4,
        now=lambda: NOW,
    )

    assert model.completed == 4
    assert result.extracted == 4
    # Writes stay on the calling thread, in selection order.
    assert list(repository.stored) == [signal.id for signal in signals]
    assert all(
        record.signal_id in {signal.id for signal in signals} for record in repository.requests
    )


CLUSTER_FIRST_ID = UUID("b3f1c2d4-0000-4000-8000-0000000000a1")
CLUSTER_SECOND_ID = UUID("b3f1c2d4-0000-4000-8000-0000000000a2")
CLUSTER_GROUP_ID = UUID("b3f1c2d4-0000-4000-8000-0000000000a3")

FIRST_BODY = "Health officials confirmed 12 cases in Hanoi."
SECOND_BODY = "The ministry reported 3 deaths on Tuesday."

CLUSTER_GOOD_RESPONSE = json.dumps(
    {
        "signal_type": "outbreak_report",
        "source_language": "en",
        "title_english": "Cholera outbreak",
        "brief": [
            {"slot": "what_where", "text": "Luanda.", "reported": True},
            {"slot": "counts", "text": "12 cases and 3 deaths.", "reported": True},
            {"slot": "timing", "text": "Tuesday.", "reported": True},
            {"slot": "spread", "text": "Locally.", "reported": True},
            {"slot": "reporting", "text": "Ministry.", "reported": True},
        ],
        "disease": {"name": "Cholera", "confidence": 0.9},
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {
            "confirmed_cases": {
                "value": 12,
                "source_span": "Health officials confirmed 12 cases in Hanoi.",
                "source_index": 0,
            },
            "deaths": {
                "value": 3,
                "source_span": "The ministry reported 3 deaths on Tuesday.",
                "source_index": 1,
            },
        },
        "confidence": 0.9,
    }
)


def test_a_cluster_is_extracted_and_recorded_as_one_cost_row_with_its_batch_size() -> None:
    cluster = ExtractableCluster(
        group_id=CLUSTER_GROUP_ID,
        representative_id=CLUSTER_FIRST_ID,
        members=(
            ClusterMemberSignal(
                id=CLUSTER_FIRST_ID, source_index=0, title="T1", raw_text=FIRST_BODY
            ),
            ClusterMemberSignal(
                id=CLUSTER_SECOND_ID, source_index=1, title="T2", raw_text=SECOND_BODY
            ),
        ),
    )
    repository = ExtractRepository(pending=(), clusters=(cluster,))
    model = ScriptedModel([CLUSTER_GOOD_RESPONSE])

    result = run_extraction(
        repository,
        model,
        guards=guards(),
        limit=10,
        now=lambda: NOW,
    )

    assert result.extracted == 1
    assert len(repository.recorded_clusters) == 1
    rep_id, member_ids, stored = repository.recorded_clusters[0]
    assert rep_id == CLUSTER_FIRST_ID
    assert member_ids == (CLUSTER_FIRST_ID, CLUSTER_SECOND_ID)
    assert stored.extraction.epidemiology.confirmed_cases.value == 12

    assert len(repository.requests) == 1
    assert repository.requests[0].batch_size == 2
    assert repository.requests[0].signal_id == CLUSTER_FIRST_ID


def test_a_cluster_rejection_falls_back_to_extracting_only_the_representative() -> None:
    cluster = ExtractableCluster(
        group_id=CLUSTER_GROUP_ID,
        representative_id=CLUSTER_FIRST_ID,
        members=(
            ClusterMemberSignal(
                id=CLUSTER_FIRST_ID, source_index=0, title="T1", raw_text=FIRST_BODY
            ),
            ClusterMemberSignal(
                id=CLUSTER_SECOND_ID, source_index=1, title="T2", raw_text=SECOND_BODY
            ),
        ),
    )
    repository = ExtractRepository(pending=(), clusters=(cluster,))

    bad_response = CLUSTER_GOOD_RESPONSE.replace('"confidence": 0.9', '"confidence": 0.1')

    single_good_response = json.dumps(
        {
            "signal_type": "outbreak_report",
            "source_language": "en",
            "title_english": "Cholera outbreak",
            "brief": [
                {"slot": "what_where", "text": "Luanda.", "reported": True},
                {"slot": "counts", "text": "12 cases.", "reported": True},
                {"slot": "timing", "text": "Tuesday.", "reported": True},
                {"slot": "spread", "text": "Locally.", "reported": True},
                {"slot": "reporting", "text": "Ministry.", "reported": True},
            ],
            "disease": {"name": "Cholera", "confidence": 0.9},
            "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
            "epidemiology": {
                "confirmed_cases": {
                    "value": 12,
                    "source_span": "Health officials confirmed 12 cases in Hanoi.",
                    "source_index": 0,
                }
            },
            "confidence": 0.9,
        }
    )

    model = ScriptedModel([bad_response, single_good_response])

    result = run_extraction(
        repository,
        model,
        guards=guards(),
        limit=10,
        now=lambda: NOW,
    )

    assert result.extracted == 1
    assert result.reviewed == 1
    assert CLUSTER_FIRST_ID in repository.stored
    assert CLUSTER_SECOND_ID not in repository.stored
    assert len(repository.recorded_clusters) == 0


def test_a_cluster_failure_to_ground_falls_back_to_extracting_only_the_representative() -> None:
    cluster = ExtractableCluster(
        group_id=CLUSTER_GROUP_ID,
        representative_id=CLUSTER_FIRST_ID,
        members=(
            ClusterMemberSignal(
                id=CLUSTER_FIRST_ID, source_index=0, title="T1", raw_text=FIRST_BODY
            ),
            ClusterMemberSignal(
                id=CLUSTER_SECOND_ID, source_index=1, title="T2", raw_text=SECOND_BODY
            ),
        ),
    )
    repository = ExtractRepository(pending=(), clusters=(cluster,))

    ungrounded_response = CLUSTER_GOOD_RESPONSE.replace(
        "Health officials confirmed 12 cases in Hanoi.", "A completely fabricated span."
    )

    single_good_response = json.dumps(
        {
            "signal_type": "outbreak_report",
            "source_language": "en",
            "title_english": "Cholera outbreak",
            "brief": [
                {"slot": "what_where", "text": "Luanda.", "reported": True},
                {"slot": "counts", "text": "12 cases.", "reported": True},
                {"slot": "timing", "text": "Tuesday.", "reported": True},
                {"slot": "spread", "text": "Locally.", "reported": True},
                {"slot": "reporting", "text": "Ministry.", "reported": True},
            ],
            "disease": {"name": "Cholera", "confidence": 0.9},
            "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
            "epidemiology": {
                "confirmed_cases": {
                    "value": 12,
                    "source_span": "Health officials confirmed 12 cases in Hanoi.",
                    "source_index": 0,
                }
            },
            "confidence": 0.9,
        }
    )

    model = ScriptedModel([ungrounded_response, single_good_response])

    result = run_extraction(
        repository,
        model,
        guards=guards(),
        limit=10,
        now=lambda: NOW,
    )

    assert result.extracted == 1
    assert result.reviewed == 1
    assert CLUSTER_FIRST_ID in repository.stored
    assert CLUSTER_SECOND_ID not in repository.stored
    assert len(repository.recorded_clusters) == 0
