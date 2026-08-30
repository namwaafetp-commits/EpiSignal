"""Storage for the pre-group stage.

The only module that writes `story_groups`. It also carries the selection
rule the stage lives or dies by: classification selection excludes deferred
members of open groups, and nothing else anywhere knows membership exists.

Selection exclusion lives in `SqlAlchemyAiRepository.awaiting_classification`,
applied unconditionally: groups exist only when the stage has written them,
so the flag that gates the writer needs no reader.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.orm import Session

from episignal_backend.db.types import ProcessingStatus, StoryGroupRole, StoryGroupState
from episignal_backend.ingestion.pregroup import PreGroup, PreGroupSignal
from episignal_backend.models import GdeltQueryRule, Signal, Source, StoryGroup, StoryGroupMember


class SqlAlchemyPreGroupStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def candidates(self, *, limit: int) -> list[PreGroupSignal]:
        """Normalized signals with their grouping facts.

        A signal whose query rule or publisher country is missing still
        arrives, with None facts: the stage groups it alone rather than
        dropping it.
        """
        rows = self._session.execute(
            select(
                Signal.id,
                Signal.first_seen_at,
                GdeltQueryRule.rule_group,
                Source.country_code,
                Source.is_official,
                Source.credibility_tier,
            )
            .join(Source, Signal.source_id == Source.id)
            .outerjoin(GdeltQueryRule, Signal.query_rule_id == GdeltQueryRule.id)
            .where(
                Signal.processing_status == ProcessingStatus.NORMALIZED,
                # A signal already carrying a membership was routed by an
                # earlier run; re-routing it would let a resolved group's
                # history be rewritten.
                ~self._member_of_any_group(),
            )
            .order_by(Signal.first_seen_at.asc(), Signal.id.asc())
            .limit(limit)
        ).all()
        return [
            PreGroupSignal(
                signal_id=row.id,
                rule_group=row.rule_group,
                country_code=row.country_code,
                source_is_official=row.is_official,
                credibility_tier=row.credibility_tier,
                first_seen_at=row.first_seen_at,
            )
            for row in rows
        ]

    def write_groups(self, groups: Sequence[PreGroup], *, window_days: int, now: datetime) -> int:
        """Persist groups with their roles. Returns groups written."""
        for group in groups:
            row = StoryGroup(
                id=uuid4(),
                rule_group=group.rule_group,
                country_code=group.country_code,
                state=StoryGroupState.OPEN,
                window_days=window_days,
                opened_at=now,
            )
            self._session.add(row)
            self._session.flush()
            self._session.add(
                StoryGroupMember(
                    group_id=row.id,
                    signal_id=group.representative.signal_id,
                    role=StoryGroupRole.REPRESENTATIVE,
                )
            )
            for member in group.deferred:
                self._session.add(
                    StoryGroupMember(
                        group_id=row.id,
                        signal_id=member.signal_id,
                        role=StoryGroupRole.DEFERRED,
                    )
                )
        return len(groups)

    def resolve_and_expire(self, *, expiry_hours: int, now: datetime) -> tuple[int, int]:
        """Close groups whose routing is finished.

        Resolved: the representative left `normalized` — classified, reviewed,
        or failed, the group has said what it had to say and its deferred
        members return to selection. Expired: the group outlived its budget
        and everything in it returns to selection untouched.
        """
        resolved_ids = list(
            self._session.execute(
                select(StoryGroup.id)
                .join(
                    StoryGroupMember,
                    (StoryGroupMember.group_id == StoryGroup.id)
                    & (StoryGroupMember.role == StoryGroupRole.REPRESENTATIVE),
                )
                .join(Signal, StoryGroupMember.signal_id == Signal.id)
                .where(
                    StoryGroup.state == StoryGroupState.OPEN,
                    Signal.processing_status != ProcessingStatus.NORMALIZED,
                )
            ).scalars()
        )
        expired_ids = list(
            self._session.execute(
                select(StoryGroup.id).where(
                    StoryGroup.state == StoryGroupState.OPEN,
                    StoryGroup.opened_at < now - timedelta(hours=expiry_hours),
                )
            ).scalars()
        )
        for group_id in resolved_ids:
            self._session.execute(
                update(StoryGroup)
                .where(StoryGroup.id == group_id)
                .values(state=StoryGroupState.RESOLVED)
            )
        for group_id in expired_ids:
            self._session.execute(
                update(StoryGroup)
                .where(StoryGroup.id == group_id)
                .values(state=StoryGroupState.EXPIRED)
            )
        return len(resolved_ids), len(expired_ids)

    def _member_of_any_group(self) -> ColumnElement[bool]:
        return (
            select(StoryGroupMember.signal_id)
            .where(StoryGroupMember.signal_id == Signal.id)
            .exists()
        )
