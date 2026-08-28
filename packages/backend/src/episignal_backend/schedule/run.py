"""Running one chain, in order, with the failure policy the design settled on.

Every stage selects its own backlog by processing_status, so a failed extraction
does not invalidate signals extracted yesterday and waiting to be geocoded. The
chain therefore runs every stage and reports which ones failed, rather than
aborting on the first.

Pure. The caller supplies the stage callables, which is what makes the ordering
and the failure policy testable without a database.
"""

from collections.abc import Callable, Mapping, Sequence

from episignal_backend.schedule.documents import ChainOutcome, StageName, StageOutcome

StageRunner = Callable[[], Mapping[str, int]]


def run_chain(
    chain: Sequence[StageName],
    runners: Mapping[StageName, StageRunner],
) -> ChainOutcome:
    outcomes: list[StageOutcome] = []

    for stage in chain:
        try:
            counts = runners[stage]()
        except Exception as error:
            # The type name only. An exception raised near the session can carry
            # the connection string, and one raised near a prompt can carry the
            # article.
            outcomes.append(StageOutcome(stage=stage, ok=False, error=type(error).__name__))
            continue
        outcomes.append(StageOutcome(stage=stage, ok=True, counts=dict(counts)))

    return ChainOutcome(outcomes=tuple(outcomes))
