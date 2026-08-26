from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from episignal_backend.ingestion.documents import RawDocument
from episignal_backend.ingestion.ecdc_epi import EcdcEpiConnector
from episignal_backend.ingestion.protocol import UnsupportedDocument

FIXTURES = Path(__file__).parent / "fixtures"
RETRIEVED = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)

NEWS_URL = (
    "https://www.ecdc.europa.eu/en/news-events/"
    "epidemiological-update-11-august-2026-imported-case-andes-hantavirus-eueea"
)
NEWS_TITLE = (
    "Epidemiological update – 11 August 2026: Imported case of Andes hantavirus in the EU/EEA"
)


def page(name: str) -> str:
    return (FIXTURES / f"ecdc_epi_{name}.html").read_text(encoding="utf-8")


def document(
    name: str,
    *,
    title: str = NEWS_TITLE,
    link: str = NEWS_URL,
    pub_date: str = "Thu, 20 Aug 2026 13:39:42 +0200",
    html: str | None = None,
    error: str | None = None,
) -> RawDocument:
    payload: dict[str, object] = {"feed": {"title": title, "link": link, "pubDate": pub_date}}
    if error is not None:
        payload["article_error"] = error
    else:
        payload["article_html"] = page(name) if html is None else html
    return RawDocument(payload=payload, retrieved_at=RETRIEVED, source_url=link)


def connector() -> EcdcEpiConnector:
    # normalize never touches the client, so no transport is needed here.
    return EcdcEpiConnector(client=None)


def test_normalize_stores_the_article_prose_as_evidence() -> None:
    signal = connector().normalize(document("news"))
    assert signal.raw_text.startswith(
        "According to the report, the person stayed in France from 19 July to 2 August"
    )
    assert len(signal.raw_text.split()) == 400


def test_normalize_excludes_navigation_badges_related_cards_and_footer() -> None:
    # The fixture carries sentinel text in each chrome region, so a change that
    # widened the extracted region would fail here rather than silently store
    # navigation as the source's own words.
    signal = connector().normalize(document("news"))
    for sentinel in ("NAVIGATION", "BADGE", "MORE ON THIS TOPIC", "FOOTER"):
        assert sentinel not in signal.raw_text


def test_normalize_reads_the_node_id_as_external_id() -> None:
    assert connector().normalize(document("news")).external_id == "42178"


def test_normalize_prefers_the_pages_canonical_url_over_the_feed_link() -> None:
    signal = connector().normalize(document("news", link="https://www.ecdc.europa.eu/en/stale"))
    assert signal.url == NEWS_URL


def test_normalize_uses_the_published_meta_tag_and_keeps_its_offset() -> None:
    # The source's own offset is preserved rather than converted to UTC, so the
    # stored timestamp still says what the publisher said.
    signal = connector().normalize(document("news"))
    assert signal.published_at.isoformat() == "2026-08-20T13:39:42+02:00"
    assert signal.published_at.utcoffset() == timedelta(hours=2)


def test_normalize_falls_back_to_the_feed_date_without_a_meta_tag() -> None:
    html = page("news").replace('property="article:published_time"', 'property="ignored"')
    signal = connector().normalize(document("news", html=html))
    assert signal.published_at.utcoffset() == timedelta(hours=2)
    assert signal.published_at.hour == 13


def test_normalize_accepts_a_recurring_overview_page() -> None:
    # dengue-monthly reports og:type "Landing Page" yet carries 1 599 words of
    # surveillance prose, which is why page type is not the filter.
    signal = connector().normalize(
        document(
            "website",
            title="Dengue worldwide overview",
            link="https://www.ecdc.europa.eu/en/dengue-monthly",
            pub_date="Mon, 10 Aug 2026 12:00:00 +0200",
        )
    )
    assert signal.raw_text.startswith("Since the beginning of 2026")
    assert len(signal.raw_text.split()) == 1599


def test_normalize_accepts_an_outbreak_page_carrying_case_counts() -> None:
    signal = connector().normalize(
        document(
            "landing",
            title="Ebola disease outbreak in the Democratic Republic of the Congo and Uganda",
            link="https://www.ecdc.europa.eu/en/ebola-outbreak-democratic-republic-congo-and-uganda",
            pub_date="Fri, 21 Aug 2026 17:36:21 +0200",
        )
    )
    assert "5 656 confirmed cases" in signal.raw_text


def test_normalize_rejects_a_page_with_no_article_body() -> None:
    with pytest.raises(UnsupportedDocument):
        connector().normalize(
            document(
                "nobody",
                title="All topics",
                link="https://www.ecdc.europa.eu/en/all-topics",
                pub_date="Sat, 01 Aug 2026 10:00:00 +0200",
            )
        )


def test_normalize_raises_a_failure_not_a_rejection_when_the_article_was_not_retrieved() -> None:
    # A retrieval failure must stay a failure: treating it as a rejection would
    # let a broken source report a clean run.
    with pytest.raises(ValueError) as raised:
        connector().normalize(document("news", error="ConnectTimeout"))
    assert not isinstance(raised.value, UnsupportedDocument)


def test_normalize_never_records_the_exception_message() -> None:
    document_with_error = document("news", error="ConnectTimeout")
    assert "article_html" not in document_with_error.payload
    assert document_with_error.payload["article_error"] == "ConnectTimeout"


def test_normalize_rejects_a_document_with_no_title() -> None:
    with pytest.raises(ValueError):
        connector().normalize(document("news", title="   "))


def test_normalize_produces_a_hash_that_changes_with_the_body() -> None:
    first = connector().normalize(document("news"))
    edited = page("news").replace("mild symptoms", "severe symptoms")
    second = connector().normalize(document("news", html=edited))
    assert first.content_hash != second.content_hash


def test_normalize_produces_a_stable_hash_for_unchanged_evidence() -> None:
    assert (
        connector().normalize(document("news")).content_hash
        == connector().normalize(document("news")).content_hash
    )


def test_normalize_marks_the_document_as_english() -> None:
    assert connector().normalize(document("news")).language == "en"
