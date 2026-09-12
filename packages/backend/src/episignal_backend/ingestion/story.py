"""Conservative deterministic grouping of articles covering one story.

Story identity is deliberately separate from epidemiologic event identity. It
may use strong textual/entity evidence even when extraction has not resolved a
disease or location. It never uses disease, country, or a discovery rule as a
positive match by itself.
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from episignal_backend.ai.documents import ExtractableSignal

STORY_WINDOW_HOURS = 48
STORY_MATCH_THRESHOLD = 0.72
_TOKEN = re.compile(r"[\w-]+", re.UNICODE)
_GENERIC_TERMS = frozenset(
    {
        "about",
        "after",
        "cases",
        "confirmed",
        "disease",
        "health",
        "including",
        "infections",
        "involving",
        "officials",
        "outbreak",
        "province",
        "report",
        "reported",
        "research",
        "same",
        "said",
        "separate",
        "study",
        "the",
        "virus",
    }
)


class StoryArticle(BaseModel):
    """Article evidence used only for deterministic story identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: UUID
    title: str = Field(min_length=1)
    raw_text: str = ""
    published_at: datetime | None = None
    first_seen_at: datetime


class StoryArticleGroup(BaseModel):
    """One conservative group of articles about the same development."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    articles: tuple[StoryArticle, ...] = Field(min_length=1)


def _timestamp(article: StoryArticle) -> datetime:
    return article.published_at or article.first_seen_at


def _distinctive_terms(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in (match.group(0).casefold() for match in _TOKEN.finditer(text))
        if len(token) >= 5 and token not in _GENERIC_TERMS
    )


def _publication_score(left: StoryArticle, right: StoryArticle) -> float:
    gap = abs(_timestamp(left) - _timestamp(right))
    if gap > timedelta(hours=STORY_WINDOW_HOURS):
        return 0.0
    return 1.0 - gap.total_seconds() / (STORY_WINDOW_HOURS * 3600)


def story_match_score(left: StoryArticle, right: StoryArticle) -> float:
    """Score textual story identity, or return zero outside its time bound."""
    time_score = _publication_score(left, right)
    if time_score == 0.0:
        return 0.0

    title_score = fuzz.token_set_ratio(left.title, right.title) / 100.0
    body_score = fuzz.token_set_ratio(left.raw_text, right.raw_text) / 100.0
    if not left.raw_text.strip() or not right.raw_text.strip():
        body_score = 0.0

    left_terms = _distinctive_terms(f"{left.title} {left.raw_text}")
    right_terms = _distinctive_terms(f"{right.title} {right.raw_text}")
    overlap = len(left_terms & right_terms)
    entity_score = min(1.0, overlap / 3.0)
    return 0.35 * title_score + 0.35 * body_score + 0.20 * entity_score + 0.10 * time_score


def _same_story(left: StoryArticle, right: StoryArticle) -> bool:
    overlap = len(
        _distinctive_terms(f"{left.title} {left.raw_text}")
        & _distinctive_terms(f"{right.title} {right.raw_text}")
    )
    title_score = fuzz.token_set_ratio(left.title, right.title) / 100.0
    body_score = (
        fuzz.token_set_ratio(left.raw_text, right.raw_text) / 100.0
        if left.raw_text.strip() and right.raw_text.strip()
        else 0.0
    )

    score = story_match_score(left, right)
    if score < STORY_MATCH_THRESHOLD and not (
        overlap >= 4 and title_score >= 0.45 and body_score >= 0.45
    ):
        return False

    # Require two independent signals of identity. This prevents same-day
    # same-disease reports from merging on generic outbreak language.
    return overlap >= 2 and (
        title_score >= 0.78
        or (title_score >= 0.62 and body_score >= 0.45)
        or (title_score >= 0.45 and overlap >= 4 and body_score >= 0.45)
    )


def group_stories(
    signals: Sequence[StoryArticle | ExtractableSignal],
) -> tuple[StoryArticleGroup, ...]:
    """Group only when every article agrees strongly with every group member."""
    articles = tuple(
        signal
        if isinstance(signal, StoryArticle)
        else StoryArticle(
            signal_id=signal.id,
            title=signal.title,
            raw_text=signal.raw_text,
            published_at=signal.published_at,
            first_seen_at=signal.first_seen_at,
        )
        for signal in signals
    )
    ordered = sorted(articles, key=lambda item: (_timestamp(item), item.signal_id.bytes))
    groups: list[list[StoryArticle]] = []
    for article in ordered:
        matching = next(
            (group for group in groups if all(_same_story(article, member) for member in group)),
            None,
        )
        if matching is None:
            groups.append([article])
        else:
            matching.append(article)
    return tuple(StoryArticleGroup(articles=tuple(group)) for group in groups)


def story_group_ids(
    signals: Sequence[ExtractableSignal],
) -> tuple[tuple[UUID, ...], ...]:
    """Return stable signal-id groups for the scheduler cohort."""
    return tuple(
        tuple(article.signal_id for article in group.articles) for group in group_stories(signals)
    )
