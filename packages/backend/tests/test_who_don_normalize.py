import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from episignal_backend.db.types import ProcessingStatus, SignalType
from episignal_backend.ingestion.documents import RawDocument
from episignal_backend.ingestion.who_don import WhoDonConnector

FIXTURE = Path(__file__).parent / "fixtures" / "who_don_sample.json"
RETRIEVED = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def documents() -> list[RawDocument]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [RawDocument(payload=item, retrieved_at=RETRIEVED) for item in payload["value"]]


def test_normalize_builds_the_public_document_url() -> None:
    signal = WhoDonConnector().normalize(documents()[0])
    assert signal.url == ("https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615")
    assert signal.canonical_url == signal.url


def test_normalize_uses_the_don_id_as_the_external_identifier() -> None:
    assert WhoDonConnector().normalize(documents()[0]).external_id == "2026-DON615"


def test_normalize_collapses_whitespace_in_the_title() -> None:
    signal = WhoDonConnector().normalize(documents()[0])
    assert signal.title == (
        "Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo"
    )


def test_normalize_joins_every_section_and_strips_markup() -> None:
    text = WhoDonConnector().normalize(documents()[0]).raw_text
    assert "<p>" not in text
    assert "<strong>" not in text
    assert "4665 confirmed cases, including 2184 deaths" in text
    assert "WHO advises against travel restrictions." in text
    assert "Vaccination & contact tracing are ongoing." in text


def test_normalize_skips_empty_and_missing_sections() -> None:
    text = WhoDonConnector().normalize(documents()[1]).raw_text
    assert text == "An earlier update on the same outbreak.\n\nNo change to advice."


def test_normalize_reads_the_publication_timestamp_as_utc() -> None:
    signal = WhoDonConnector().normalize(documents()[0])
    assert signal.published_at == datetime(2026, 8, 14, 15, 38, 29, tzinfo=UTC)
    assert signal.retrieved_at == RETRIEVED


def test_normalize_leaves_the_document_unprocessed() -> None:
    signal = WhoDonConnector().normalize(documents()[0])
    assert signal.processing_status is ProcessingStatus.FETCHED
    assert signal.signal_type is SignalType.UNKNOWN
    assert signal.language == "en"


def test_normalize_produces_a_stable_content_hash() -> None:
    connector = WhoDonConnector()
    first = connector.normalize(documents()[0])
    second = connector.normalize(documents()[0])
    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64


def test_normalize_rejects_a_document_without_a_url_name() -> None:
    broken = RawDocument(payload={"Title": "x"}, retrieved_at=RETRIEVED)
    with pytest.raises(ValueError, match="UrlName"):
        WhoDonConnector().normalize(broken)


def test_connector_names_the_seeded_source() -> None:
    assert WhoDonConnector().source_name == "WHO Disease Outbreak News"
