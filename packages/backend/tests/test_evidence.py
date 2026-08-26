from datetime import UTC, datetime
from uuid import UUID

from episignal_backend.evidence import query_evidence_page
from episignal_backend.models import Signal
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

SOURCE_ONE = UUID("9b2340c7-62be-4557-88a4-1b951bbd6e1f")
SOURCE_TWO = UUID("f6504d90-e04b-4ee9-b236-b8918129caa8")


def sqlite_session() -> Session:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE sources (id CHAR(32) PRIMARY KEY, name TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE signals (
                id CHAR(32) PRIMARY KEY,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                source_id CHAR(32) NOT NULL,
                external_id TEXT,
                url TEXT NOT NULL,
                canonical_url TEXT,
                title TEXT NOT NULL,
                raw_text TEXT,
                summary TEXT,
                published_at DATETIME,
                retrieved_at DATETIME NOT NULL,
                language VARCHAR(8),
                content_hash VARCHAR(64) NOT NULL,
                relevance_score FLOAT,
                public_health_relevant BOOLEAN,
                signal_type VARCHAR(32) NOT NULL,
                ai_extraction JSON,
                ai_model TEXT,
                ai_processed_at DATETIME,
                processing_status VARCHAR(32) NOT NULL
            )
            """
        )
        connection.execute(
            text("INSERT INTO sources (id, name) VALUES (:id, :name)"),
            [
                {"id": SOURCE_ONE.hex, "name": "WHO Disease Outbreak News"},
                {"id": SOURCE_TWO.hex, "name": "Africa CDC"},
            ],
        )
    return Session(engine)


def signal(
    *, signal_id: str, source_id: UUID, title: str, published_at: datetime, raw_text: str | None
) -> Signal:
    return Signal(
        id=UUID(signal_id),
        created_at=published_at,
        updated_at=published_at,
        source_id=source_id,
        url=f"https://example.test/{signal_id}",
        title=title,
        raw_text=raw_text,
        published_at=published_at,
        retrieved_at=published_at,
        content_hash=signal_id.replace("-", "") * 2,
    )


def test_query_pages_exact_evidence_newest_first_with_live_counts() -> None:
    session = sqlite_session()
    session.add_all(
        [
            signal(
                signal_id="11111111-1111-1111-1111-111111111111",
                source_id=SOURCE_ONE,
                title="Newest evidence",
                published_at=datetime(2026, 8, 14, tzinfo=UTC),
                raw_text="Newest exact text",
            ),
            signal(
                signal_id="22222222-2222-2222-2222-222222222222",
                source_id=SOURCE_TWO,
                title="Middle evidence",
                published_at=datetime(2026, 8, 1, tzinfo=UTC),
                raw_text="Middle exact text",
            ),
            signal(
                signal_id="33333333-3333-3333-3333-333333333333",
                source_id=SOURCE_ONE,
                title="Oldest evidence",
                published_at=datetime(2026, 7, 1, tzinfo=UTC),
                raw_text="Oldest exact text",
            ),
            signal(
                signal_id="44444444-4444-4444-4444-444444444444",
                source_id=SOURCE_TWO,
                title="Not evidence",
                published_at=datetime(2026, 8, 20, tzinfo=UTC),
                raw_text=None,
            ),
        ]
    )
    session.commit()

    page = query_evidence_page(session, limit=1, offset=1)

    assert page.total == 3
    assert page.source_count == 2
    assert page.limit == 1
    assert page.offset == 1
    assert [item.title for item in page.items] == ["Middle evidence"]
    assert page.items[0].source_name == "Africa CDC"
    assert page.items[0].raw_text == "Middle exact text"
    session.close()
