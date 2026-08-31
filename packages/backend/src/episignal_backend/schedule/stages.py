"""Each stage, as the chain calls it.

Every function here calls the same domain function the matching runner calls.
The runners' own `main` and `_run` parse argv, print, and return exit codes,
none of which belong inside a chain.

Each stage opens its own session. That is deliberate: a stage that fails must
not roll back the stages that already succeeded, and the advisory lock is held
on a different connection for the whole run.
"""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from episignal_backend.ai.extract import run_extraction
from episignal_backend.ai.ladder import Guards, cost_row
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.ai.routing import NoProviderKey, routed_from_settings
from episignal_backend.ai.triage import run_triage
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.db.types import AiPurpose
from episignal_backend.events.assemble import run_event_assembly
from episignal_backend.events.delta import configure_delta
from episignal_backend.events.documents import EventForSummary, SummarySource
from episignal_backend.events.repository import SqlAlchemyEventRepository
from episignal_backend.events.summarize import (
    SummaryOutcome,
    SummaryResult,
    configure_summary,
    pick_representative_sources,
    run_summary,
    should_resummarize,
    unique_summary_candidates,
)
from episignal_backend.ingestion.dedupe import DedupeThresholds, run_dedupe
from episignal_backend.ingestion.discovery import run_discovery
from episignal_backend.ingestion.gdelt.api import GdeltDocClient
from episignal_backend.ingestion.gdelt.article import ArticleFetcher
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.pipeline import run_ingestion
from episignal_backend.ingestion.protocol import SourceConnector
from episignal_backend.ingestion.repository import (
    SqlAlchemyDedupeRepository,
    SqlAlchemyDiscoveryRepository,
    SqlAlchemySignalRepository,
)
from episignal_backend.ingestion.retrieval import run_retrieval
from episignal_backend.ingestion.who_don import WhoDonConnector
from episignal_backend.schedule.documents import DiscoveryWindow, StageName
from episignal_backend.schedule.run import StageRunner

SUMMARY_MAX_WORKERS = 4


def _ingest(connector: SourceConnector) -> Mapping[str, int]:
    with session_scope() as session:
        result = run_ingestion(SqlAlchemySignalRepository(session), connector, since=None)
    return {
        "inserted": result.inserted,
        "skipped": result.skipped,
        "rejected": result.rejected,
        "failed": result.failed,
    }


def _discover(window: DiscoveryWindow) -> Mapping[str, int]:
    settings = get_settings()
    connector = GdeltConnector(
        search=GdeltDocClient(),
        fetcher=ArticleFetcher(
            delay_seconds=settings.gdelt_article_delay_seconds,
            user_agent=settings.gdelt_user_agent,
            timeout_seconds=settings.gdelt_article_timeout_seconds,
        ),
    )
    with session_scope() as session:
        repository = SqlAlchemyDiscoveryRepository(session)
        discovered = run_discovery(
            repository,
            connector,
            now=window.end,
            window_minutes=window.minutes,
            max_articles=settings.gdelt_max_articles_per_run,
        )
    return {
        "window_minutes": window.minutes,
        "rules": discovered.rules_run,
        "rules_failed": discovered.rules_failed,
        "discovered": discovered.discovered,
        "duplicate": discovered.duplicate,
        "rejected": discovered.rejected,
        "stored": discovered.stored,
        "failed": discovered.failed,
    }


def _retrieve() -> Mapping[str, int]:
    settings = get_settings()
    connector = GdeltConnector(
        search=GdeltDocClient(),
        fetcher=ArticleFetcher(
            delay_seconds=settings.gdelt_article_delay_seconds,
            user_agent=settings.gdelt_user_agent,
            timeout_seconds=settings.gdelt_article_timeout_seconds,
        ),
    )
    with session_scope() as session:
        result = run_retrieval(
            SqlAlchemyDiscoveryRepository(session),
            connector,
            max_attempts=settings.gdelt_max_retrieval_attempts,
            batch_size=settings.gdelt_retry_batch_size,
            window_hours=settings.stage0_candidate_window_hours,
        )
    return {
        "examined": result.examined,
        "filtered": result.filtered,
        "retrieved": result.retrieved,
        "duplicates": result.duplicates,
        "redundant": result.redundant,
        "still_failing": result.still_failing,
        "failed": result.failed,
    }


def _dedupe() -> Mapping[str, int]:
    settings = get_settings()
    with session_scope() as session:
        result = run_dedupe(
            SqlAlchemyDedupeRepository(session),
            thresholds=DedupeThresholds(
                title=settings.stage0_title_similarity,
                body=settings.stage0_body_similarity,
                shingle_size=settings.stage0_shingle_size,
                near_exact_title=settings.stage0_near_exact_title_similarity,
                near_exact_window_hours=settings.stage0_near_exact_window_hours,
            ),
            window_hours=settings.stage0_candidate_window_hours,
            batch_size=settings.stage0_batch_size,
        )
    return {
        "examined": result.examined,
        "primaries": result.primaries,
        "duplicates": result.duplicates,
        "failed": result.failed,
    }


def _triage() -> Mapping[str, int]:
    settings = get_settings()
    guards = Guards(
        max_requests=settings.ai_max_requests_per_run,
        max_cost_usd=settings.ai_max_cost_usd_per_run,
    )

    with session_scope() as session:
        repository = SqlAlchemyAiRepository(session)
        try:
            model = routed_from_settings(settings, list(repository.models()))
        except NoProviderKey as error:
            raise RuntimeError(str(error)) from error
        result = run_triage(
            repository,
            model,
            guards=guards,
            limit=settings.ai_triage_batch_limit,
            max_tier=settings.ai_max_tier,
        )
    return {
        "examined": result.examined,
        "triaged": result.triaged,
        "repaired": result.repaired,
        "filtered": result.filtered,
        "failed": result.failed,
        "unavailable": result.unavailable,
        "requests": result.requests,
    }


def _extract() -> Mapping[str, int]:
    settings = get_settings()
    guards = Guards(
        max_requests=settings.ai_max_requests_per_run,
        max_cost_usd=settings.ai_max_cost_usd_per_run,
    )

    with session_scope() as session:
        repository = SqlAlchemyAiRepository(session)
        try:
            model = routed_from_settings(settings, list(repository.models()))
        except NoProviderKey as error:
            raise RuntimeError(str(error)) from error
        # The relevance pass is gone from the chain: the keyword gate decides
        # relevance in the retrieve stage, for zero model requests. The pass
        # itself is kept in `ai/classify.py` so a rollback is one line here.
        extracted = run_extraction(
            repository,
            model,
            guards=guards,
            limit=settings.ai_signal_batch_limit,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
            min_confidence=settings.ai_min_confidence,
            workers=settings.ai_extraction_workers,
        )
    return {
        "examined": extracted.examined,
        "extracted": extracted.extracted,
        "rejected": extracted.reviewed,
        "unavailable": extracted.unavailable,
        "requests": extracted.requests,
    }


def _match() -> Mapping[str, int]:
    settings = get_settings()
    with session_scope() as session:
        event_repository = SqlAlchemyEventRepository(session)
        specs = list(SqlAlchemyAiRepository(session).models())
        # The delta pass is enrichment: without a provider key the assembly
        # still runs, it simply never records what changed.
        wiring = configure_delta(settings, specs)
        summary = run_event_assembly(
            event_repository,
            limit=settings.event_match_batch_size,
            stale=False,
            cluster_window_days=settings.event_cluster_window_days,
            cluster_distance_km=settings.event_cluster_distance_km,
            match_threshold=settings.event_match_threshold,
            review_threshold=None,
            match_recency_days=settings.event_match_recency_days,
            match_distance_km=settings.event_match_distance_km,
            candidate_lookback_days=settings.event_lookback_days,
            candidate_limit=settings.event_candidate_limit,
            delta_model=wiring.model,
            delta_spec=wiring.spec,
            followup_window_days=wiring.window_days,
        )
    return {
        "seen": summary.signals_seen,
        "clusters": summary.clusters_built,
        "created": summary.events_created,
        "attached": summary.signals_attached,
        "refused": summary.signals_refused,
        "unclusterable": summary.unclusterable,
        "deltas": summary.deltas_applied,
    }


def _summarize() -> Mapping[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    with session_scope() as session:
        event_repository = SqlAlchemyEventRepository(session)
        specs = list(SqlAlchemyAiRepository(session).models())
        wiring = configure_summary(settings, specs)
        awaiting = event_repository.events_awaiting_summary(
            limit=settings.event_match_batch_size,
            max_age_hours=settings.resummary_max_age_hours,
        )

        examined = 0
        skipped = 0
        summarized = 0
        failed = 0
        unavailable = 0

        pending: list[tuple[EventForSummary, tuple[SummarySource, ...]]] = []
        for event in unique_summary_candidates(awaiting):
            examined += 1
            if not should_resummarize(
                last_summarized_at=event.last_summarized_at,
                latest_observation=event.latest_observation,
                previous_counts=event.previous_counts,
                unsummarized_articles=event.unsummarized_articles,
                now=now,
                max_age_hours=settings.resummary_max_age_hours,
                new_article_count=settings.resummary_new_article_count,
            ):
                skipped += 1
                continue

            if wiring.model is None or wiring.spec is None:
                skipped += 1
                continue

            sources = pick_representative_sources(
                event.sources,
                max_sources=settings.summary_max_sources,
            )
            pending.append((event, sources))

        if pending and wiring.model is not None and wiring.spec is not None:
            model = wiring.model
            spec = wiring.spec

            def summarize_one(
                item: tuple[EventForSummary, tuple[SummarySource, ...]],
            ) -> SummaryResult:
                event, sources = item
                return run_summary(model, spec, event=event, sources=sources)

            # Model calls are independent. The four-worker cap bounds provider
            # pressure; each completed future is written and committed before
            # the next completion is handled.
            with ThreadPoolExecutor(max_workers=SUMMARY_MAX_WORKERS) as pool:
                futures = {pool.submit(summarize_one, item): item for item in pending}
                for future in as_completed(futures):
                    event, sources = futures[future]
                    result = future.result()
                    if result.attempt is not None:
                        event_repository.record_ai_request(
                            cost_row(
                                result.attempt,
                                purpose=AiPurpose.EVENT_SUMMARY,
                                signal_id=None,
                                batch_size=1,
                                at=now,
                            )
                        )
                    if result.outcome is SummaryOutcome.ACCEPTED and result.verdict is not None:
                        event_repository.store_summary(
                            event_id=event.event_id,
                            headline=result.verdict.headline,
                            summary=result.verdict.summary,
                            status=result.verdict.status.value,
                            latest_development=result.verdict.latest_development,
                            uncertainties=list(result.verdict.uncertainties),
                            model_id=spec.model_id,
                            source_signal_ids=[source.signal_id for source in sources],
                            counts=event.latest_observation,
                            now=now,
                        )
                        summarized += 1
                    elif result.outcome is SummaryOutcome.UNAVAILABLE:
                        unavailable += 1
                    else:
                        failed += 1
                    event_repository.commit()

        event_repository.commit()

    return {
        "examined": examined,
        "skipped": skipped,
        "summarized": summarized,
        "failed": failed,
        "unavailable": unavailable,
    }


def build_stage_runners(*, window: DiscoveryWindow) -> dict[StageName, StageRunner]:
    """Map each stage to a callable. Nothing here runs until the chain calls it."""
    return {
        StageName.INGEST_WHO: lambda: _ingest(WhoDonConnector()),
        StageName.DISCOVER: lambda: _discover(window),
        StageName.RETRIEVE: _retrieve,
        StageName.DEDUPE: _dedupe,
        StageName.TRIAGE: _triage,
        StageName.EXTRACT: _extract,
        StageName.MATCH: _match,
        StageName.SUMMARIZE: _summarize,
    }
