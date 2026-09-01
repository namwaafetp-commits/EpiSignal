from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from episignal_backend.db.types import DiscoveryMethod, ProcessingStatus
from episignal_backend.ingestion.documents import DiscoveredSignal, Publisher
from episignal_backend.ingestion.protocol import DiscoveryRepository
from episignal_backend.ingestion.repository import (
    SqlAlchemyDiscoveryRepository,
    build_discovered_signal,
)

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
FIRST = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)


def discovered(**overrides: object) -> DiscoveredSignal:
    values: dict[str, object] = {
        "url": "https://example.vn/a",
        "canonical_url": "https://example.vn/a",
        "title": "18 students hospitalised",
        "raw_text": "Eighteen students were admitted.",
        "published_at": NOW,
        "published_at_offset_minutes": 420,
        "retrieved_at": NOW,
        "first_seen_at": FIRST,
        "gdelt_seen_at": SEEN,
        "language": "vi",
        "content_hash": "c" * 64,
        "publisher": Publisher(
            domain="example.vn", name="Example News", language="vi", country_code="VN"
        ),
    }
    return DiscoveredSignal(**(values | overrides))  # type: ignore[arg-type]


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def all(self) -> Any:
        return self._value

    def scalars(self) -> Any:
        return self._value


class FakeSession:
    """Answers `execute` from a queue and assigns ids on flush.

    The real session cannot be used: the primary key defaults to
    `gen_random_uuid()`, which only PostgreSQL provides.
    """

    def __init__(
        self,
        results: list[Any],
        stored: dict[UUID, Any] | None = None,
        flush_error: Exception | None = None,
    ) -> None:
        self.results = results
        self.stored = stored or {}
        self.flush_error = flush_error
        self.added: list[Any] = []
        self.executed: list[Any] = []
        self.rollbacks = 0

    def execute(self, statement: Any) -> FakeResult:
        self.executed.append(statement)
        return FakeResult(self.results.pop(0) if self.results else None)

    def get(self, model: Any, identity: UUID) -> Any:
        return self.stored.get(identity)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()

    def rollback(self) -> None:
        self.rollbacks += 1


def test_a_discovered_signal_is_marked_as_discovered_via_gdelt() -> None:
    row = build_discovered_signal(discovered(), uuid4())
    assert row.discovered_via is DiscoveryMethod.GDELT


def test_a_discovered_signal_keeps_all_four_timestamps_apart() -> None:
    row = build_discovered_signal(discovered(), uuid4())
    assert row.published_at == NOW
    assert row.first_seen_at == FIRST
    assert row.retrieved_at == NOW
    assert row.gdelt_seen_at == SEEN
    assert row.published_at_offset_minutes == 420


def test_a_stub_carries_no_body_and_no_publication_time() -> None:
    row = build_discovered_signal(
        discovered(
            raw_text=None,
            published_at=None,
            published_at_offset_minutes=None,
            processing_status=ProcessingStatus.NEEDS_REVIEW,
        ),
        uuid4(),
    )
    assert row.raw_text is None
    assert row.published_at is None
    assert row.processing_status is ProcessingStatus.NEEDS_REVIEW


def publisher() -> Publisher:
    return Publisher(domain="example.vn", name="Example News", language="vi", country_code="VN")


def test_a_known_domain_reuses_its_existing_source() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    existing = uuid4()
    session = FakeSession([existing])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    assert repository.publisher_source_id(publisher()) == existing
    assert session.added == []


def test_an_unknown_domain_registers_a_local_media_source() -> None:
    from episignal_backend.db.types import CredibilityTier, SourceType
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    # No source for the domain, and no source holding the display name.
    session = FakeSession([None, None])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    source_id = repository.publisher_source_id(publisher())

    registered = session.added[0]
    assert registered.id == source_id
    assert registered.domain == "example.vn"
    assert registered.name == "Example News"
    assert registered.base_url == "https://example.vn"
    assert registered.source_type is SourceType.LOCAL_MEDIA
    assert registered.credibility_tier is CredibilityTier.UNKNOWN
    # A discovered publisher is never official: only an official body can
    # confirm, and GDELT finding an article grants no authority.
    assert registered.is_official is False


def test_a_colliding_publisher_name_falls_back_to_the_domain() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    # No source for the domain, but the display name is already taken.
    session = FakeSession([None, uuid4()])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    repository.publisher_source_id(publisher())

    # A shared display name is cosmetic; a lost discovery is not.
    assert session.added[0].name == "example.vn"
    assert session.added[0].domain == "example.vn"


def stub_row(attempts: int = 1) -> Any:
    from episignal_backend.db.types import DiscoveryMethod
    from episignal_backend.models import Signal

    return Signal(
        id=uuid4(),
        source_id=uuid4(),
        url="https://example.vn/a",
        canonical_url="https://example.vn/a",
        title="Report",
        raw_text=None,
        retrieved_at=NOW,
        first_seen_at=FIRST,
        gdelt_seen_at=SEEN,
        language="vi",
        content_hash="d" * 64,
        discovered_via=DiscoveryMethod.GDELT,
        retrieval_attempts=attempts,
        processing_status=ProcessingStatus.NEEDS_REVIEW,
    )


def test_a_stub_is_offered_for_retry_with_its_original_first_seen_time() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    session = FakeSession([[(stub_row(), "example.vn", "VN")]])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    stubs = repository.stubs_awaiting_retrieval(max_attempts=3, limit=10)

    assert len(stubs) == 1
    # A retry must never reset the clock the lead-time metric is measured from.
    assert stubs[0].first_seen_at == FIRST
    assert stubs[0].attempts == 1
    assert stubs[0].article.domain == "example.vn"
    assert stubs[0].article.gdelt_seen_at == SEEN


def test_a_stub_with_no_seen_time_is_not_offered_for_retry() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    row = stub_row()
    row.gdelt_seen_at = None
    session = FakeSession([[(row, "example.vn", "VN")]])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    assert repository.stubs_awaiting_retrieval(max_attempts=3, limit=10) == ()


def test_promotion_replaces_the_stub_content_and_counts_the_attempt() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    row = stub_row()
    session = FakeSession([None], stored={row.id: row})
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    assert repository.promote(row.id, discovered()) is True
    assert row.raw_text == "Eighteen students were admitted."
    assert row.published_at == NOW
    assert row.processing_status is ProcessingStatus.FETCHED
    assert row.retrieval_attempts == 2


def test_a_promotion_conflict_leaves_the_stub_intact() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository
    from sqlalchemy.exc import IntegrityError

    row = stub_row()
    session = FakeSession(
        [],
        stored={row.id: row},
        flush_error=IntegrityError("duplicate", None, Exception("duplicate")),
    )
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    # A redundant stub is left alone rather than deleted on a guess.
    assert repository.promote(row.id, discovered()) is False
    assert session.rollbacks == 1


def test_a_failed_attempt_is_recorded_without_touching_content() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    row = stub_row()
    session = FakeSession([None], stored={row.id: row})
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    repository.record_failed_attempt(row.id, max_attempts=5)

    assert row.retrieval_attempts == 2
    assert row.raw_text is None


def test_seen_urls_asks_nothing_when_given_nothing() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    session = FakeSession([])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    # An empty IN clause is both wasteful and, on some drivers, invalid.
    assert repository.seen_urls(()) == frozenset()


def _conforms(repository: DiscoveryRepository) -> DiscoveryRepository:
    # mypy checks this structurally, signatures included. isinstance below only
    # checks that the member NAMES exist, so it cannot stand in for this.
    return repository


def test_repository_satisfies_the_protocol() -> None:
    repository = SqlAlchemyDiscoveryRepository(session=None)  # type: ignore[arg-type]
    assert isinstance(repository, DiscoveryRepository)
    assert _conforms(repository) is repository


def test_active_filter_rules_are_returned_as_contracts() -> None:
    from episignal_backend.db.types import FilterRuleGroup
    from episignal_backend.models import SignalFilterRule

    row = SignalFilterRule(
        rule_group=FilterRuleGroup.TITLE_EXCLUSION,
        pattern=r"\bviral video\b",
        label="Viral content",
        active=True,
    )
    row.id = uuid4()
    session = FakeSession([[row]])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    rules = repository.filter_rules()

    assert len(rules) == 1
    assert rules[0].pattern == r"\bviral video\b"
    assert rules[0].rule_group is FilterRuleGroup.TITLE_EXCLUSION
    assert rules[0].id == row.id


def test_recording_a_rejection_issues_one_statement() -> None:
    from episignal_backend.ingestion.documents import Rejection

    session = FakeSession([])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    repository.record_rejection(
        Rejection(
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Outbreak of violence in the capital",
            domain="example.com",
            gdelt_seen_at=SEEN,
            rejected_at=NOW,
            filter_rule_id=uuid4(),
        )
    )

    assert len(session.executed) == 1


def test_initial_contentless_discovery_is_stored_as_a_fetchable_signal() -> None:
    from episignal_backend.models import Signal

    # Retrieval is deferred; a bodyless discovery has not failed yet.
    stub_signal = discovered(raw_text=None, processing_status=ProcessingStatus.FETCHED)
    session = FakeSession([])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    repository.add(stub_signal, uuid4())

    signals = [obj for obj in session.added if isinstance(obj, Signal)]
    assert len(signals) == 1
    assert signals[0].processing_status is ProcessingStatus.FETCHED
    assert signals[0].raw_text is None


def test_record_failed_attempt_opens_retrieval_failed_when_max_attempts_reached() -> None:
    row = stub_row(attempts=2)
    session = FakeSession([], stored={row.id: row})
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    repository.record_failed_attempt(row.id, max_attempts=3)

    assert row.retrieval_attempts == 3
    assert row.processing_status is ProcessingStatus.FAILED


def test_promotion_does_not_manage_human_review_cases() -> None:
    from episignal_backend.db.types import ReviewReason, ReviewStatus
    from episignal_backend.models.review import SignalReviewCase

    row = stub_row()
    open_case = SignalReviewCase(
        id=uuid4(),
        signal_id=row.id,
        reason=ReviewReason.RETRIEVAL_FAILED,
        status=ReviewStatus.OPEN,
        opened_at=NOW,
    )
    session = FakeSession([open_case], stored={row.id: row})
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    assert repository.promote(row.id, discovered()) is True
    assert open_case.status is ReviewStatus.OPEN


def test_promotion_does_not_close_non_retrieval_case() -> None:

    row = stub_row()
    # Non-retrieval cases are not closed because query filters by RETRIEVAL_FAILED
    session = FakeSession([None], stored={row.id: row})
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    assert repository.promote(row.id, discovered()) is True


DEFERRED_SIGNAL_ID = uuid4()


def deferred_signal_row() -> Any:
    from episignal_backend.db.types import DiscoveryMethod
    from episignal_backend.models import Signal

    return Signal(
        id=DEFERRED_SIGNAL_ID,
        source_id=uuid4(),
        url="https://example.vn/deferred",
        canonical_url="https://example.vn/deferred",
        title="Deferred Report",
        raw_text=None,
        retrieved_at=NOW,
        first_seen_at=FIRST,
        gdelt_seen_at=SEEN,
        language="vi",
        content_hash="f" * 64,
        discovered_via=DiscoveryMethod.GDELT,
        retrieval_attempts=0,
        processing_status=ProcessingStatus.CLASSIFIED,
        public_health_relevant=True,
    )


def test_keyword_rules_union_the_seed_and_the_disease_vocabulary() -> None:
    from episignal_backend.db.types import FilterRuleGroup
    from episignal_backend.models import SignalFilterRule

    rule_row = SignalFilterRule(
        rule_group=FilterRuleGroup.TITLE_INCLUSION,
        pattern="outbreak",
        label="Context: outbreak",
        active=True,
    )
    rule_row.id = uuid4()

    session = FakeSession([[rule_row], [("Cholera", ["evd", "cholera"])]])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    rules = repository.keyword_rules()
    patterns = {rule.pattern for rule in rules}

    assert "outbreak" in patterns  # a seeded title_inclusion row
    assert "cholera" in patterns  # a diseases.canonical_name, case-folded
    assert all(rule.rule_group is FilterRuleGroup.TITLE_INCLUSION for rule in rules)


def test_a_disease_synonym_is_also_a_keyword() -> None:
    session = FakeSession([[], [("Ebola virus disease", ["ebola", "evd"])]])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    patterns = {rule.pattern for rule in repository.keyword_rules()}

    assert "ebola" in patterns


def test_gated_signals_awaiting_retrieval_are_bodyless_and_fetched() -> None:
    row = deferred_signal_row()
    session = FakeSession([[(row, "example.vn", "VN")]])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    waiting = repository.gated_awaiting_retrieval(max_attempts=3, limit=10)

    assert {item.signal_id for item in waiting} == {DEFERRED_SIGNAL_ID}


def test_gated_retrieval_query_requires_completed_relevant_classification() -> None:
    session = FakeSession([[]])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    repository.gated_awaiting_retrieval(max_attempts=3, limit=10)

    rendered = str(session.executed[0].compile(compile_kwargs={"literal_binds": True}))
    assert "processing_status = 'classified'" in rendered
    assert "public_health_relevant IS true" in rendered


def test_a_filtered_signal_is_never_selected_for_retrieval() -> None:
    session = FakeSession([None, []])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    repository.record_filtered(DEFERRED_SIGNAL_ID)

    assert repository.gated_awaiting_retrieval(max_attempts=3, limit=10) == ()


def test_recording_filtered_preserves_the_row() -> None:
    from episignal_backend.models import Signal
    from sqlalchemy import Update

    class UpdatingFakeSession(FakeSession):
        def execute(self, statement: Any) -> Any:
            self.executed.append(statement)
            if isinstance(statement, Update):
                for row in self.stored.values():
                    row.processing_status = ProcessingStatus.FILTERED
            return FakeResult(self.results.pop(0) if self.results else None)

    row = deferred_signal_row()
    session = UpdatingFakeSession([None], stored={row.id: row})
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    repository.record_filtered(row.id)

    res = session.get(Signal, row.id)
    assert res is not None
    assert res.processing_status is ProcessingStatus.FILTERED
    assert res.title == "Deferred Report"
    assert res.url == "https://example.vn/deferred"


def test_the_retry_pass_only_sees_fetched_stubs() -> None:
    from sqlalchemy import Select

    session = FakeSession([[]])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    repository.stubs_awaiting_retrieval(max_attempts=3, limit=10)

    statement = session.executed[0]
    assert isinstance(statement, Select)
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert f"signals.processing_status = '{ProcessingStatus.FETCHED.value}'" in rendered
