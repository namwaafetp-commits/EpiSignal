"""Stage 0, gate three: decide from the title whether an article is worth fetching.

Positive-only, and the mirror image of `filtering.py`. That gate rejects on an
explicit exclusion; this one keeps on explicit evidence and is deliberately
generous about what counts as evidence, because a filtered measles story costs
more than an extra extraction.

Matching is case-folded substring rather than a pattern: an inclusion keyword
is a word an epidemiologist would recognise, not an expression a reviewer has
to debug. An empty rule set passes everything, so the gate can never be the
reason a run stores nothing.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import FilterRule


@dataclass(frozen=True)
class GateDecision:
    """Pass with the rule that vouched for the title, or filter with nothing.

    A rejection carries no rule because it is the absence of every rule; there
    is nothing to attribute it to but the title, which is stored.
    """

    passed: bool
    rule: FilterRule | None = None


def classify_title(title: str, rules: Sequence[FilterRule]) -> GateDecision:
    inclusions = [rule for rule in rules if rule.rule_group is FilterRuleGroup.TITLE_INCLUSION]
    if not inclusions:
        # No configured evidence is not evidence of absence.
        return GateDecision(passed=True)

    needle = " ".join(title.split()).casefold()
    for rule in inclusions:
        if rule.pattern.casefold() in needle:
            return GateDecision(passed=True, rule=rule)

    return GateDecision(passed=False)
