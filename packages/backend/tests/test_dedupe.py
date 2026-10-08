from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from episignal_backend.ingestion.dedupe import DedupeThresholds, run_dedupe
from episignal_backend.ingestion.documents import ComparableSignal

FIXTURES = Path(__file__).parent / "fixtures"
FIRST = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
LATER = FIRST + timedelta(hours=2)


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def signal(
    *,
    title: str = "Dos residentes no vacunados mueren de sarampion en Pensilvania",
    body: str | None = None,
    content_hash: str | None = None,
    first_seen_at: datetime = FIRST,
    published_at: datetime | None = None,
    identifier: UUID | None = None,
    duplicate_of: UUID | None = None,
) -> ComparableSignal:
    return ComparableSignal(
        id=identifier or uuid4(),
        canonical_url=f"https://example.com/{uuid4()}",
        title=title,
        raw_text=body or read("syndicated_body_a.txt"),
        content_hash=content_hash or ("a" * 64),
        first_seen_at=first_seen_at,
        published_at=published_at,
        duplicate_of_signal_id=duplicate_of,
    )


class FakeRepository:
    def __init__(
        self,
        queue: Sequence[ComparableSignal] = (),
        pool: Sequence[ComparableSignal] = (),
    ) -> None:
        self.queue = tuple(queue)
        self.pool = tuple(pool)
        self.duplicates: list[tuple[UUID, UUID]] = []
        self.normalized: list[UUID] = []
        self.commits = 0
        self.rollbacks = 0
        self.failing = False

    def pending(self, *, limit: int) -> Sequence[ComparableSignal]:
        return self.queue[:limit]

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> Sequence[ComparableSignal]:
        return tuple(item for item in self.pool if item.id != signal.id)

    def primary_of(self, signal_id: UUID) -> UUID:
        for item in self.pool:
            if item.id == signal_id and item.duplicate_of_signal_id is not None:
                return self.primary_of(item.duplicate_of_signal_id)
        return signal_id

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None:
        if self.failing:
            raise RuntimeError("write failed")
        self.duplicates.append((signal_id, primary_id))

    def mark_normalized(self, signal_id: UUID) -> None:
        if self.failing:
            raise RuntimeError("write failed")
        self.normalized.append(signal_id)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_a_lone_signal_is_normalized() -> None:
    alone = signal()
    repository = FakeRepository(queue=(alone,), pool=(alone,))

    result = run_dedupe(repository)

    assert repository.normalized == [alone.id]
    assert result.primaries == 1
    assert result.duplicates == 0


def test_an_identical_hash_at_another_url_is_a_duplicate() -> None:
    primary = signal(first_seen_at=FIRST)
    copy = signal(first_seen_at=LATER, title="Something else entirely")
    copy = copy.model_copy(update={"content_hash": primary.content_hash})
    repository = FakeRepository(queue=(copy,), pool=(primary, copy))

    result = run_dedupe(repository)

    assert repository.duplicates == [(copy.id, primary.id)]
    assert result.duplicates == 1


def test_a_syndicated_copy_matches_on_title_and_body() -> None:
    primary = signal(
        title=(
            "Dos residentes no vacunados mueren de sarampion en Pensilvania "
            "- Telemundo Dallas ( 39 )"
        ),
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
    )
    copy = signal(
        title=(
            "Dos residentes no vacunados mueren de sarampion en Pensilvania "
            "- Telemundo New York ( 47 )"
        ),
        body=read("syndicated_body_b.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
    )
    repository = FakeRepository(queue=(copy,), pool=(primary, copy))

    run_dedupe(repository)

    assert repository.duplicates == [(copy.id, primary.id)]


def test_an_independent_report_sharing_a_headline_is_not_a_duplicate() -> None:
    primary = signal(
        title="Two unvaccinated residents die of measles in Pennsylvania",
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
    )
    independent = signal(
        title="Two unvaccinated residents die of measles in Pennsylvania",
        body=read("independent_body.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
    )
    repository = FakeRepository(queue=(independent,), pool=(primary, independent))

    run_dedupe(repository)

    assert repository.duplicates == []
    assert repository.normalized == [independent.id]


def test_the_earliest_sighting_is_the_primary() -> None:
    earlier = signal(content_hash="a" * 64, first_seen_at=FIRST)
    later = signal(content_hash="a" * 64, first_seen_at=LATER)
    repository = FakeRepository(queue=(later,), pool=(earlier, later))

    run_dedupe(repository)

    assert repository.duplicates == [(later.id, earlier.id)]


def test_published_at_breaks_a_tie_on_first_seen_at() -> None:
    earlier = signal(content_hash="a" * 64, first_seen_at=FIRST, published_at=FIRST)
    later = signal(content_hash="a" * 64, first_seen_at=FIRST, published_at=LATER)
    repository = FakeRepository(queue=(later,), pool=(earlier, later))

    run_dedupe(repository)

    assert repository.duplicates == [(later.id, earlier.id)]


def test_a_pointer_is_flattened_to_the_terminal_primary() -> None:
    root = signal(content_hash="a" * 64, first_seen_at=FIRST)
    middle = signal(
        content_hash="a" * 64,
        first_seen_at=FIRST + timedelta(hours=1),
        duplicate_of=root.id,
    )
    newest = signal(content_hash="a" * 64, first_seen_at=LATER)
    repository = FakeRepository(queue=(newest,), pool=(middle, newest))

    run_dedupe(repository)

    # middle is the only candidate, but it points at root, so newest must too.
    assert repository.duplicates == [(newest.id, root.id)]


def test_a_write_failure_is_counted_without_abandoning_the_batch() -> None:
    first = signal(content_hash="a" * 64)
    second = signal(content_hash="b" * 64, title="Cholera cases rise in Juba")
    repository = FakeRepository(queue=(first, second), pool=(first, second))
    repository.failing = True

    result = run_dedupe(repository)

    assert result.failed == 2
    assert repository.rollbacks == 2


def test_tightening_the_body_threshold_prevents_a_match() -> None:
    primary = signal(
        title=(
            "Dos residentes no vacunados mueren de sarampion en Pensilvania "
            "- Telemundo Dallas ( 39 )"
        ),
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
    )
    copy = signal(
        title=(
            "Dos residentes no vacunados mueren de sarampion en Pensilvania "
            "- Telemundo New York ( 47 )"
        ),
        body=read("syndicated_body_b.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
    )
    repository = FakeRepository(queue=(copy,), pool=(primary, copy))

    # The titles still agree exactly, so this isolates the body threshold: at
    # 0.99 the affiliate boilerplate is enough to keep the pair apart.
    run_dedupe(repository, thresholds=DedupeThresholds(title=1.0, body=0.99))

    assert repository.duplicates == []
    assert repository.normalized == [copy.id]


def test_a_syndicated_copy_within_the_near_exact_window_is_a_duplicate() -> None:
    primary = signal(
        title=(
            "Dos residentes no vacunados mueren de sarampion en Pensilvania "
            "- Telemundo Dallas ( 39 )"
        ),
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
        published_at=FIRST,
    )
    copy = signal(
        title=(
            "Dos residentes no vacunados mueren de sarampion en Pensilvania "
            "- Telemundo New York ( 47 )"
        ),
        body=read("syndicated_body_b.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
        published_at=LATER,
    )
    repository = FakeRepository(queue=(copy,), pool=(primary, copy))

    run_dedupe(repository)

    assert repository.duplicates == [(copy.id, primary.id)]


def test_prefetch_dedupe_can_reject_a_metadata_only_syndicated_copy() -> None:
    primary = signal(
        title="Measles outbreak spreads in Hanoi",
        body=None,
        first_seen_at=FIRST,
    ).model_copy(update={"raw_text": "", "published_at": None})
    copy = signal(
        title="Measles outbreak spreads in Hanoi | Example News",
        body=None,
        first_seen_at=LATER,
    ).model_copy(update={"raw_text": "", "published_at": None})
    repository = FakeRepository(queue=(copy,), pool=(primary, copy))

    run_dedupe(repository, metadata_only=True)

    assert repository.duplicates == [(copy.id, primary.id)]


def test_a_near_exact_title_farther_than_the_window_is_not_a_duplicate() -> None:
    primary = signal(
        title="A cholera outbreak reported in Juba",
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
        published_at=FIRST,
    )
    weeks_later = signal(
        title="A cholera outbreak reported in Juba - follow-up",
        body=read("independent_body.txt"),
        content_hash="b" * 64,
        first_seen_at=FIRST + timedelta(days=5),
        published_at=FIRST + timedelta(days=5),
    )
    repository = FakeRepository(queue=(weeks_later,), pool=(primary, weeks_later))

    run_dedupe(repository)

    assert repository.duplicates == []
    assert repository.normalized == [weeks_later.id]


def test_an_identical_title_outside_the_near_exact_band_needs_the_body() -> None:
    primary = signal(
        title="Two unvaccinated residents die of measles in Pennsylvania",
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
        published_at=FIRST,
    )
    independent = signal(
        title="Two unvaccinated residents die of measles in Pennsylvania",
        body=read("independent_body.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
        published_at=LATER,
    )
    repository = FakeRepository(queue=(independent,), pool=(primary, independent))

    # Identical titles are excluded from the near-exact band (ratio == 100),
    # so an independent body is still corroboration, not a duplicate.
    run_dedupe(repository)

    assert repository.duplicates == []
    assert repository.normalized == [independent.id]


def test_unrelated_titles_inside_the_near_exact_window_are_not_duplicates() -> None:
    primary = signal(
        title="Dengue cases rise in Chiang Mai",
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        published_at=FIRST,
    )
    unrelated = signal(
        title="Dengue cases rise in Phuket",
        body=read("independent_body.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
        published_at=LATER,
    )
    repository = FakeRepository(queue=(unrelated,), pool=(primary, unrelated))

    run_dedupe(repository)

    assert repository.duplicates == []
    assert repository.normalized == [unrelated.id]


@pytest.mark.parametrize("value", [-0.1, 100.1])
def test_near_exact_threshold_rejects_values_outside_rapidfuzz_scale(value: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        DedupeThresholds(near_exact_title=value)
