"""Read-only access to stored source evidence."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from episignal_backend.models import Signal, Source


@dataclass(frozen=True)
class EvidenceSignal:
    id: UUID
    source_name: str
    title: str
    raw_text: str
    url: str
    published_at: datetime | None
    retrieved_at: datetime


@dataclass(frozen=True)
class EvidencePage:
    items: tuple[EvidenceSignal, ...]
    total: int
    source_count: int
    limit: int
    offset: int


def query_evidence_page(session: Session, *, limit: int = 20, offset: int = 0) -> EvidencePage:
    has_evidence = func.length(func.trim(Signal.raw_text)) > 0
    total, source_count = session.execute(
        select(func.count(Signal.id), func.count(distinct(Signal.source_id))).where(has_evidence)
    ).one()
    rows = session.execute(
        select(Signal, Source.name)
        .join(Source, Signal.source_id == Source.id)
        .where(has_evidence)
        .order_by(
            Signal.published_at.desc().nullslast(),
            Signal.retrieved_at.desc(),
            Signal.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    items_list: list[EvidenceSignal] = []
    for signal, source_name in rows:
        raw_text = signal.raw_text
        assert raw_text is not None
        items_list.append(
            EvidenceSignal(
                id=signal.id,
                source_name=source_name,
                title=signal.title,
                raw_text=raw_text,
                url=signal.url,
                published_at=signal.published_at,
                retrieved_at=signal.retrieved_at,
            )
        )
    return EvidencePage(
        items=tuple(items_list),
        total=total,
        source_count=source_count,
        limit=limit,
        offset=offset,
    )
