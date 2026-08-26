from datetime import UTC, datetime

import pytest
from episignal_backend.db.types import ProcessingStatus, SignalType
from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from pydantic import ValidationError

MOMENT = datetime(2026, 8, 14, 15, 38, 29, tzinfo=UTC)


def valid_signal(**overrides: object) -> NormalizedSignal:
    fields: dict[str, object] = {
        "external_id": "2026-DON615",
        "url": "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615",
        "canonical_url": ("https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"),
        "title": "Ebola disease - Democratic Republic of the Congo",
        "raw_text": "4665 confirmed cases, including 2184 deaths.",
        "published_at": MOMENT,
        "retrieved_at": MOMENT,
        "language": "en",
        "content_hash": "a" * 64,
    }
    fields.update(overrides)
    return NormalizedSignal(**fields)  # type: ignore[arg-type]


def test_normalized_signal_defaults_to_unprocessed_state() -> None:
    signal = valid_signal()
    assert signal.signal_type is SignalType.UNKNOWN
    assert signal.processing_status is ProcessingStatus.FETCHED


def test_normalized_signal_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        valid_signal(summary="a summary the extraction slice has not produced")


def test_normalized_signal_rejects_a_naive_published_at() -> None:
    with pytest.raises(ValidationError):
        valid_signal(published_at=datetime(2026, 8, 14, 15, 38, 29))


def test_normalized_signal_rejects_an_empty_title() -> None:
    with pytest.raises(ValidationError):
        valid_signal(title="   ")


def test_normalized_signal_is_frozen() -> None:
    signal = valid_signal()
    with pytest.raises(ValidationError):
        signal.title = "changed"  # type: ignore[misc]


def test_raw_document_keeps_the_untouched_source_payload() -> None:
    document = RawDocument(payload={"Title": "x", "UrlName": "y"}, retrieved_at=MOMENT)
    assert document.payload["UrlName"] == "y"
    assert document.retrieved_at == MOMENT


def test_normalized_signal_rejects_an_overlong_language_tag() -> None:
    with pytest.raises(ValidationError):
        valid_signal(language="zh-Hans-CN-x-private")


def test_normalized_signal_rejects_a_non_hex_content_hash() -> None:
    with pytest.raises(ValidationError):
        valid_signal(content_hash="A" * 64)


def test_normalized_signal_rejects_a_blank_url() -> None:
    with pytest.raises(ValidationError):
        valid_signal(url="   ")


def test_raw_document_rejects_a_naive_retrieved_at() -> None:
    with pytest.raises(ValidationError):
        RawDocument(payload={}, retrieved_at=datetime(2026, 8, 14, 15, 38, 29))


def test_raw_document_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RawDocument(payload={}, retrieved_at=MOMENT, bogus=1)  # type: ignore[call-arg]
