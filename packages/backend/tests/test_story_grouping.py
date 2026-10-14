"""Regression fixtures for conservative same-story grouping."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.ai.documents import ExtractableSignal
from episignal_backend.ingestion.story import group_stories

BASE = datetime(2026, 9, 1, 12, tzinfo=UTC)


def article(title: str, body: str, *, days: int = 0) -> ExtractableSignal:
    return ExtractableSignal(
        id=uuid4(),
        title=title,
        raw_text=body,
        published_at=BASE + timedelta(days=days),
        first_seen_at=BASE + timedelta(days=days),
    )


def test_same_anthropic_report_with_unresolved_identity_is_one_story() -> None:
    articles = [
        article(
            "Anthropic blocks AI users over suspected bioweapons research",
            "Anthropic said it blocked users who sought help with biological weapons "
            "research, including chikungunya and avian influenza.",
        ),
        article(
            "Anthropic Blocks AI Misuse for Biological Weapons Research",
            "Anthropic reported misuse of its AI models in biological weapons inquiries "
            "involving chikungunya and orthopoxviruses.",
        ),
        article(
            "Anthropic Blocks AI Misuse for Biological Weapons Research Including "
            "Chikungunya Virus",
            "The company described blocking users asking about chikungunya virus and "
            "other biological weapons research.",
        ),
        article(
            "Anthropic reports misuse of AI models for biological weapons research",
            "Anthropic said the misuse report covered biological weapons research and "
            "chikungunya virus inquiries.",
        ),
    ]

    groups = group_stories(articles)

    assert [len(group.articles) for group in groups] == [4]


def test_strong_story_identity_allows_disease_disagreement() -> None:
    groups = group_stories(
        [
            article(
                "Anthropic report details AI misuse for biological weapons",
                "Anthropic described biological weapons inquiries involving a broad "
                "infectious diseases category.",
            ),
            article(
                "Anthropic blocks users after chikungunya bioweapons inquiries",
                "The same Anthropic report identified chikungunya virus among biological "
                "weapons research requests.",
            ),
        ]
    )

    assert len(groups) == 1


def test_same_disease_distinct_outbreaks_remain_two_stories() -> None:
    groups = group_stories(
        [
            article(
                "Dengue outbreak reported in Province A",
                "Health officials reported a dengue outbreak in Province A after 18 infections.",
            ),
            article(
                "Dengue outbreak reported in Province B",
                "Health officials reported a separate dengue outbreak in Province B after "
                "21 infections.",
            ),
        ]
    )

    assert len(groups) == 2


def test_same_disease_unresolved_unrelated_stories_remain_two_stories() -> None:
    groups = group_stories(
        [
            article(
                "Dengue cases rise after flooding",
                "Officials reported more dengue cases after flooding, but no event location "
                "was identified.",
            ),
            article(
                "Dengue vaccine study publishes early laboratory results",
                "Researchers described laboratory dengue vaccine findings without reporting "
                "an active outbreak.",
            ),
        ]
    )

    assert len(groups) == 2


def test_different_diseases_unrelated_stories_remain_two_stories() -> None:
    groups = group_stories(
        [
            article("Cholera cluster reported", "Officials investigated a cholera cluster."),
            article("Measles cases confirmed", "Officials confirmed measles cases."),
        ]
    )

    assert len(groups) == 2


def test_weak_similarity_remains_separate() -> None:
    groups = group_stories(
        [
            article("Outbreak update", "Officials shared a brief outbreak update."),
            article("Health news", "A separate health report was published."),
        ]
    )

    assert len(groups) == 2


def test_same_report_from_publishers_is_one_story_with_multiple_sources() -> None:
    groups = group_stories(
        [
            article(
                "WHO confirms cholera outbreak in Luanda",
                "The World Health Organization confirmed a cholera outbreak in Luanda after "
                "42 cases.",
            ),
            article(
                "Reuters: cholera outbreak confirmed in Luanda",
                "Reuters reported that the World Health Organization confirmed a cholera "
                "outbreak in Luanda after 42 cases.",
            ),
            article(
                "BBC reports WHO cholera outbreak confirmation in Luanda",
                "BBC said the World Health Organization confirmed a cholera outbreak in "
                "Luanda after 42 cases.",
            ),
        ]
    )

    assert len(groups) == 1
    assert len(groups[0].articles) == 3


def test_different_update_three_days_later_is_new_story() -> None:
    groups = group_stories(
        [
            article(
                "Dengue outbreak announced in Cebu",
                "Officials announced a dengue outbreak in Cebu after 12 confirmed cases.",
            ),
            article(
                "Vaccination campaign starts in Cebu after dengue outbreak",
                "A vaccination campaign started in Cebu three days after the dengue "
                "outbreak was announced.",
                days=3,
            ),
        ]
    )

    assert len(groups) == 2
