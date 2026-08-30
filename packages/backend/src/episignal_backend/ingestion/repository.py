"""SQLAlchemy implementation of the storage boundary.

Kept deliberately thin: it translates a `NormalizedSignal` into a `Signal` row
and answers existence questions. All ingestion decisions live in `pipeline.py`,
which never imports this module.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from episignal_backend.db.types import (
    CredibilityTier,
    DiscoveryMethod,
    FilterRuleGroup,
    ProcessingStatus,
    ReviewReason,
    SourceType,
)
from episignal_backend.ingestion.documents import (
    ComparableSignal,
    DiscoveredArticle,
    DiscoveredSignal,
    FilterRule,
    NormalizedSignal,
    Publisher,
    QueryRule,
    Rejection,
    StubRetrieval,
)
from episignal_backend.ingestion.normalize_title import normalize_title
from episignal_backend.models import (
    Disease,
    GdeltQueryRule,
    RejectedSighting,
    Signal,
    SignalFilterRule,
    Source,
)
from episignal_backend.review.repository import SqlAlchemyReviewRepository


def build_signal(signal: NormalizedSignal, source_id: UUID) -> Signal:
    return Signal(
        source_id=source_id,
        external_id=signal.external_id,
        url=signal.url,
        canonical_url=signal.canonical_url,
        title=signal.title,
        normalized_title=normalize_title(signal.title),
        raw_text=signal.raw_text,
        published_at=signal.published_at,
        retrieved_at=signal.retrieved_at,
        # An official document's first sighting is the retrieval that produced
        # this version; there is no earlier discovery step to inherit from.
        first_seen_at=signal.retrieved_at,
        language=signal.language,
        content_hash=signal.content_hash,
        signal_type=signal.signal_type,
        processing_status=signal.processing_status,
    )


def build_discovered_signal(signal: DiscoveredSignal, source_id: UUID) -> Signal:
    return Signal(
        source_id=source_id,
        url=signal.url,
        canonical_url=signal.canonical_url,
        title=signal.title,
        normalized_title=normalize_title(signal.title),
        raw_text=signal.raw_text,
        published_at=signal.published_at,
        published_at_offset_minutes=signal.published_at_offset_minutes,
        retrieved_at=signal.retrieved_at,
        first_seen_at=signal.first_seen_at,
        gdelt_seen_at=signal.gdelt_seen_at,
        language=signal.language,
        content_hash=signal.content_hash,
        discovered_via=DiscoveryMethod.GDELT,
        query_rule_id=signal.query_rule_id,
        processing_status=signal.processing_status,
    )


def build_comparable(signal: Signal) -> ComparableSignal:
    return ComparableSignal(
        id=signal.id,
        canonical_url=signal.canonical_url or signal.url,
        title=signal.title,
        # Callers only ever select rows where this is not null; the assertion
        # documents that rather than silently substituting an empty string.
        raw_text=signal.raw_text or "",
        content_hash=signal.content_hash,
        first_seen_at=signal.first_seen_at,
        published_at=signal.published_at,
        duplicate_of_signal_id=signal.duplicate_of_signal_id,
    )


class SqlAlchemySignalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def source_id(self, name: str) -> UUID | None:
        return self._session.execute(
            select(Source.id).where(Source.name == name)
        ).scalar_one_or_none()

    def exists(self, url: str, content_hash: str) -> bool:
        found = self._session.execute(
            select(Signal.id).where(Signal.url == url, Signal.content_hash == content_hash).limit(1)
        ).first()
        return found is not None

    def add(self, signal: NormalizedSignal, source_id: UUID) -> None:
        self._session.add(build_signal(signal, source_id))
        self._session.flush()

    def activate(self, source_id: UUID) -> None:
        self._session.execute(update(Source).where(Source.id == source_id).values(active=True))

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


class SqlAlchemyDiscoveryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def active_rules(self) -> Sequence[QueryRule]:
        rows = self._session.execute(
            select(GdeltQueryRule)
            .where(GdeltQueryRule.active.is_(True))
            .order_by(GdeltQueryRule.rule_group, GdeltQueryRule.label)
        ).scalars()
        return tuple(
            QueryRule(
                id=row.id,
                rule_group=row.rule_group,
                query=row.query,
                label=row.label,
                language=row.language,
            )
            for row in rows
        )

    def filter_rules(self) -> Sequence[FilterRule]:
        rows = self._session.execute(
            select(SignalFilterRule)
            .where(SignalFilterRule.active.is_(True))
            .order_by(SignalFilterRule.rule_group, SignalFilterRule.label)
        ).scalars()
        return tuple(
            FilterRule(
                id=row.id,
                rule_group=row.rule_group,
                pattern=row.pattern,
                label=row.label,
            )
            for row in rows
        )

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

    def gated_awaiting_retrieval(self, *, max_attempts: int, limit: int) -> Sequence[StubRetrieval]:
        """Discoveries stored without a body, waiting for the gate.

        Distinct from `stubs_awaiting_retrieval`, which serves articles whose
        page already failed. These have never been asked for.
        """
        return self._retrievals(ProcessingStatus.FETCHED, max_attempts=max_attempts, limit=limit)

    def record_filtered(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.FILTERED)
        )

    def title_duplicate_of(self, normalized_title: str, *, within_hours: int) -> UUID | None:
        cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
        return self._session.execute(
            select(Signal.id)
            .where(
                Signal.normalized_title == normalized_title,
                Signal.first_seen_at >= cutoff,
                Signal.raw_text.is_not(None),
                Signal.processing_status != ProcessingStatus.DUPLICATE,
            )
            .order_by(Signal.first_seen_at, Signal.id)
            .limit(1)
        ).scalar_one_or_none()

    def mark_title_duplicate(self, signal_id: UUID, primary_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.DUPLICATE,
                duplicate_of_signal_id=primary_id,
            )
        )

    def record_rejection(self, rejection: Rejection) -> None:
        # Conflict-do-nothing: the same article is sighted in several
        # consecutive windows, and one row per article is the useful record.
        statement = (
            pg_insert(RejectedSighting)
            .values(
                url=rejection.url,
                canonical_url=rejection.canonical_url,
                title=rejection.title,
                domain=rejection.domain,
                gdelt_seen_at=rejection.gdelt_seen_at,
                rejected_at=rejection.rejected_at,
                filter_rule_id=rejection.filter_rule_id,
            )
            .on_conflict_do_nothing(index_elements=[RejectedSighting.canonical_url])
        )
        self._session.execute(statement)

    def seen_urls(self, canonical_urls: Sequence[str]) -> frozenset[str]:

        if not canonical_urls:
            return frozenset()
        found = self._session.execute(
            select(Signal.canonical_url).where(Signal.canonical_url.in_(tuple(canonical_urls)))
        ).scalars()
        return frozenset(url for url in found if url is not None)

    def first_seen_at(self, canonical_url: str) -> datetime | None:
        return self._session.execute(
            select(func.min(Signal.first_seen_at)).where(Signal.canonical_url == canonical_url)
        ).scalar_one_or_none()

    def publisher_source_id(self, publisher: Publisher) -> UUID:
        existing = self._session.execute(
            select(Source.id).where(Source.domain == publisher.domain)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        taken = self._session.execute(
            select(Source.id).where(Source.name == publisher.name)
        ).scalar_one_or_none()
        # A display name shared with another outlet is cosmetic; refusing to
        # register the publisher would lose the discovery entirely.
        name = publisher.domain if taken is not None else publisher.name

        source = Source(
            name=name,
            source_type=SourceType.LOCAL_MEDIA,
            country_code=publisher.country_code,
            base_url=f"https://{publisher.domain}",
            domain=publisher.domain,
            credibility_tier=CredibilityTier.UNKNOWN,
            is_official=False,
            language=publisher.language or "en",
            active=True,
        )
        self._session.add(source)
        try:
            self._session.flush()
        except IntegrityError:
            # A concurrent run registered the same domain first. Its row is as
            # good as ours.
            self._session.rollback()
            return self._session.execute(
                select(Source.id).where(Source.domain == publisher.domain)
            ).scalar_one()
        return source.id

    def add(self, signal: DiscoveredSignal, source_id: UUID) -> None:
        db_signal = build_discovered_signal(signal, source_id)
        self._session.add(db_signal)
        self._session.flush()
        if (
            db_signal.processing_status == ProcessingStatus.NEEDS_REVIEW
            or db_signal.raw_text is None
        ):
            SqlAlchemyReviewRepository(self._session).open_review(
                db_signal.id, reason=ReviewReason.RETRIEVAL_FAILED
            )

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

        stubs: list[StubRetrieval] = []
        for signal, domain, country_code in rows:
            if signal.gdelt_seen_at is None:
                continue
            stubs.append(
                StubRetrieval(
                    signal_id=signal.id,
                    article=DiscoveredArticle(
                        url=signal.url,
                        canonical_url=signal.canonical_url or signal.url,
                        title=signal.title,
                        domain=domain,
                        gdelt_seen_at=signal.gdelt_seen_at,
                        language=signal.language,
                        country_code=country_code,
                        query_rule_id=signal.query_rule_id,
                    ),
                    first_seen_at=signal.first_seen_at,
                    attempts=signal.retrieval_attempts,
                )
            )
        return tuple(stubs)

    def promote(self, signal_id: UUID, signal: DiscoveredSignal) -> bool:
        stub = self._session.get(Signal, signal_id)
        if stub is None:
            return False

        stub.title = signal.title
        stub.raw_text = signal.raw_text
        stub.published_at = signal.published_at
        stub.published_at_offset_minutes = signal.published_at_offset_minutes
        stub.retrieved_at = signal.retrieved_at
        stub.content_hash = signal.content_hash
        stub.processing_status = signal.processing_status
        stub.retrieval_attempts = stub.retrieval_attempts + 1
        try:
            self._session.flush()
        except IntegrityError:
            # A full version of this URL already carries that hash, so the stub
            # is redundant rather than promotable. It is left exactly as it was:
            # a spare row costs less than deleting one on a guess.
            self._session.rollback()
            return False
        SqlAlchemyReviewRepository(self._session).recover_retrieval_automatically(signal_id)
        return True

    def record_failed_attempt(self, signal_id: UUID, *, max_attempts: int = 3) -> None:
        stub = self._session.get(Signal, signal_id)
        if stub is not None:
            stub.retrieval_attempts = stub.retrieval_attempts + 1
            if stub.retrieval_attempts >= max_attempts:
                stub.processing_status = ProcessingStatus.NEEDS_REVIEW
                SqlAlchemyReviewRepository(self._session).open_review(
                    signal_id, reason=ReviewReason.RETRIEVAL_FAILED
                )
        else:
            self._session.execute(
                update(Signal)
                .where(Signal.id == signal_id)
                .values(retrieval_attempts=Signal.retrieval_attempts + 1)
            )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


class SqlAlchemyDedupeRepository:
    """Storage for Stage 0's second gate.

    Deliberately unable to discover or fetch: this pass reads stored signals and
    writes their status, and nothing else.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def pending(self, *, limit: int) -> Sequence[ComparableSignal]:
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.FETCHED,
                # Stubs stay in the retry path: a document with no body cannot
                # be compared on one, and comparing on the title alone is the
                # merge this design refuses.
                Signal.raw_text.is_not(None),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        ).scalars()
        return tuple(build_comparable(row) for row in rows)

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> Sequence[ComparableSignal]:
        span = timedelta(hours=window_hours)
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.id != signal.id,
                Signal.raw_text.is_not(None),
                or_(
                    # An identical hash is compared regardless of age, so a late
                    # republication of unchanged text is still caught.
                    Signal.content_hash == signal.content_hash,
                    and_(
                        Signal.first_seen_at >= signal.first_seen_at - span,
                        Signal.first_seen_at <= signal.first_seen_at + span,
                    ),
                ),
            )
            .order_by(Signal.first_seen_at)
        ).scalars()
        return tuple(build_comparable(row) for row in rows)

    def primary_of(self, signal_id: UUID) -> UUID:
        seen: set[UUID] = set()
        current = signal_id
        while current not in seen:
            seen.add(current)
            parent = self._session.execute(
                select(Signal.duplicate_of_signal_id).where(Signal.id == current)
            ).scalar_one_or_none()
            if parent is None:
                return current
            current = parent
        # Unreachable while pointers are flattened on assignment. Returning the
        # last id rather than looping forever keeps a corrupted row survivable.
        return current

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.DUPLICATE,
                duplicate_of_signal_id=primary_id,
            )
        )

    def mark_normalized(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.NORMALIZED)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
