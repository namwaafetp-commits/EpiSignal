import json
from uuid import UUID, uuid4

from episignal_backend.ai.documents import (
    ClassifiableSignal,
    ClusterMemberSignal,
    ExtractableSignal,
)
from episignal_backend.ai.prompts import (
    MAX_CLUSTER_MEMBERS,
    classification_prompt,
    cluster_extraction_prompt,
    extraction_prompt,
    truncate,
)

FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")


def test_truncation_stops_at_a_whitespace_boundary() -> None:
    assert truncate("one two three four", 11) == "one two"


def test_text_shorter_than_the_limit_is_untouched() -> None:
    assert truncate("one two", 100) == "one two"


def test_truncation_of_text_with_no_whitespace_still_bounds_the_length() -> None:
    assert len(truncate("a" * 50, 10)) == 10


def test_an_extraction_prompt_carries_the_schema_and_the_article() -> None:
    signal = ExtractableSignal(
        id=FIRST, title="Cholera cases rise", raw_text="327 confirmed cases were recorded."
    )

    system, user = extraction_prompt(signal, max_characters=1000)

    assert "source_span" in system
    assert "327 confirmed cases were recorded." in user
    assert "Cholera cases rise" in user


def test_an_extraction_prompt_forbids_inventing_a_number() -> None:
    signal = ExtractableSignal(id=FIRST, title="t", raw_text="body")

    system, _ = extraction_prompt(signal, max_characters=1000)

    assert "null" in system


def test_an_extraction_prompt_truncates_a_long_article() -> None:
    signal = ExtractableSignal(id=FIRST, title="t", raw_text="word " * 500)

    _, user = extraction_prompt(signal, max_characters=100)

    assert len(user) < 400


def test_a_classification_prompt_addresses_every_signal_by_id() -> None:
    batch = (
        ClassifiableSignal(id=FIRST, title="Cholera cases rise", excerpt="Health officials said"),
    )

    _, user = classification_prompt(batch)

    assert str(FIRST) in user
    assert "Cholera cases rise" in user


def test_a_classification_prompt_sends_titles_only() -> None:
    """The relevance gate is intentionally cheap: the headline decides, and the
    unsure-means-relevant rule protects recall."""
    batch = (ClassifiableSignal(id=FIRST, title="Cholera cases rise", excerpt="word " * 200),)

    _, user = classification_prompt(batch)

    assert "excerpt" not in user
    assert len(user) < 200


def test_the_extraction_system_prompt_contains_the_generated_schema() -> None:
    signal = ExtractableSignal(id=FIRST, title="t", raw_text="body")

    system, _ = extraction_prompt(signal, max_characters=100)

    assert json.loads(system[system.index("{") :])["additionalProperties"] is False


def test_the_extraction_prompt_asks_for_english() -> None:
    system, _ = extraction_prompt(
        ExtractableSignal(id=uuid4(), title="Choléra à Luanda", raw_text="Un article."),
        max_characters=500,
    )

    assert "English" in system


def test_the_extraction_prompt_forbids_translating_a_span() -> None:
    system, _ = extraction_prompt(
        ExtractableSignal(id=uuid4(), title="Choléra à Luanda", raw_text="Un article."),
        max_characters=500,
    )

    assert "Do not translate a span" in system


def test_the_extraction_prompt_carries_the_five_slots() -> None:
    system, _ = extraction_prompt(
        ExtractableSignal(id=uuid4(), title="Cholera in Luanda", raw_text="An article."),
        max_characters=500,
    )

    for slot in ("what_where", "counts", "timing", "spread", "reporting"):
        assert slot in system


MEMBERS = (
    ClusterMemberSignal(
        id=uuid4(),
        source_index=0,
        title="Title 1",
        raw_text="Health officials confirmed 12 cases in Hanoi.",
    ),
    ClusterMemberSignal(
        id=uuid4(),
        source_index=1,
        title="Title 2",
        raw_text="The ministry reported 3 deaths on Tuesday.",
    ),
)

LONG_MEMBERS = (
    ClusterMemberSignal(id=uuid4(), source_index=0, title="T1", raw_text="word " * 100),
    ClusterMemberSignal(id=uuid4(), source_index=1, title="T2", raw_text="word " * 100),
)


def test_a_cluster_prompt_labels_every_member() -> None:
    system, user = cluster_extraction_prompt(MEMBERS, max_characters=4000)

    assert "SOURCE 0" in user
    assert "SOURCE 1" in user
    assert "source_index" in system


def test_a_cluster_prompt_truncates_each_member_separately() -> None:
    _, user = cluster_extraction_prompt(LONG_MEMBERS, max_characters=100)

    for member in LONG_MEMBERS:
        assert member.raw_text not in user
    assert "SOURCE 1" in user


def test_a_cluster_prompt_carries_no_more_than_four_members() -> None:
    assert MAX_CLUSTER_MEMBERS == 4
