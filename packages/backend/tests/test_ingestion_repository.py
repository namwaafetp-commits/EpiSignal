from datetime import UTC, datetime
from uuid import uuid4

from episignal_backend.db.types import ProcessingStatus, SignalType
from episignal_backend.ingestion.documents import NormalizedSignal
from episignal_backend.ingestion.protocol import SignalRepository
from episignal_backend.ingestion.repository import SqlAlchemySignalRepository, build_signal

MOMENT = datetime(2026, 8, 14, 15, 38, 29, tzinfo=UTC)
URL = "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"


def sample() -> NormalizedSignal:
    return NormalizedSignal(
        external_id="2026-DON615",
        url=URL,
        canonical_url=URL,
        title="Ebola disease - Democratic Republic of the Congo",
        raw_text="4665 confirmed cases.",
        published_at=MOMENT,
        retrieved_at=MOMENT,
        content_hash="b" * 64,
    )


def _conforms(repository: SignalRepository) -> SignalRepository:
    # mypy checks this structurally, signatures included. isinstance below only
    # checks that the member NAMES exist, so it cannot stand in for this.
    return repository


def test_sqlalchemy_repository_satisfies_the_protocol() -> None:
    repository = SqlAlchemySignalRepository(session=None)  # type: ignore[arg-type]
    assert isinstance(repository, SignalRepository)
    assert _conforms(repository) is repository


def test_build_signal_maps_every_normalized_field() -> None:
    source_id = uuid4()
    signal = build_signal(sample(), source_id)
    assert signal.source_id == source_id
    assert signal.url == URL
    assert signal.canonical_url == URL
    assert signal.external_id == "2026-DON615"
    assert signal.title == "Ebola disease - Democratic Republic of the Congo"
    assert signal.raw_text == "4665 confirmed cases."
    assert signal.published_at == MOMENT
    assert signal.retrieved_at == MOMENT
    assert signal.language == "en"
    assert signal.content_hash == "b" * 64
    assert signal.signal_type is SignalType.UNKNOWN
    assert signal.processing_status is ProcessingStatus.FETCHED


def test_build_signal_leaves_later_slices_columns_empty() -> None:
    signal = build_signal(sample(), uuid4())
    assert signal.summary is None
    assert signal.relevance_score is None
    assert signal.public_health_relevant is None
    assert signal.ai_extraction is None
    assert signal.ai_model is None
    assert signal.ai_processed_at is None
