"""Stage 0, gate one: decide whether an article is worth fetching.

Negative-only by design. An article is rejected when it matches an explicit
exclusion and never for failing to prove itself relevant, because a wrongly
rejected article leaves no body, no extraction and no signal, and nothing
downstream can notice it is missing. A wrongly kept article costs one page
fetch.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import DiscoveredArticle, FilterRule

logger = logging.getLogger("episignal_backend.ingestion.filtering")


@dataclass(frozen=True)
class CompiledRules:
    """Rules prepared once per run.

    `invalid` counts the patterns that would not compile. They are skipped
    rather than raised: one malformed rule must not silence the rest.
    """

    titles: tuple[tuple[re.Pattern[str], FilterRule], ...] = ()
    domains: tuple[tuple[str, FilterRule], ...] = ()
    invalid: int = 0


def compile_rules(rules: Sequence[FilterRule]) -> CompiledRules:
    titles: list[tuple[re.Pattern[str], FilterRule]] = []
    domains: list[tuple[str, FilterRule]] = []
    invalid = 0

    for rule in rules:
        if rule.rule_group is FilterRuleGroup.DOMAIN_BLOCKLIST:
            # A host, never a regular expression: a dot in a domain is a literal
            # separator, and treating it as "any character" would reject
            # lookalikes the rule never named.
            domains.append((rule.pattern.strip().lower(), rule))
            continue
        try:
            titles.append((re.compile(rule.pattern, re.IGNORECASE), rule))
        except re.error:
            invalid += 1
            logger.warning("Filter rule %s has an invalid pattern and was skipped", rule.label)

    return CompiledRules(titles=tuple(titles), domains=tuple(domains), invalid=invalid)


def evaluate(article: DiscoveredArticle, rules: CompiledRules) -> FilterRule | None:
    """Return the rule that rejects this article, or None to keep it."""
    for blocked, rule in rules.domains:
        # Exact host or dotted suffix, so example.com covers news.example.com
        # but never notexample.com.
        if article.domain == blocked or article.domain.endswith(f".{blocked}"):
            return rule

    for pattern, rule in rules.titles:
        if pattern.search(article.title):
            return rule

    return None
