"""Each stage, as the chain calls it.

Every function here calls the same domain function the matching runner calls.
The runners' own `main` and `_run` parse argv, print, and return exit codes,
none of which belong inside a chain.

Each stage opens its own session. That is deliberate: a stage that fails must
not roll back the stages that already succeeded, and the advisory lock is held
on a different connection for the whole run.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from episignal_backend.ai.embed import run_embedding
from episignal_backend.ai.embeddings import LocalBgeM3Provider
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
from episignal_backend.events.judge import configure_judge
from episignal_backend.events.repository import SqlAlchemyEventRepository
from episignal_backend.events.summarize import (
    SummaryOutcome,
    configure_summary,
    pick_representative_sources,
    run_summary,
    should_resummarize,
    unique_summary_candidates,
)
from episignal_backend.geocode.external import NominatimClient
from episignal_backend.geocode.locate import run_geocoding
from episignal_backend.geocode.repository import (
    SqlAlchemyGazetteerRepository,
    SqlAlchemyGeocodeCacheRepository,
    SqlAlchemyGeocodeRepository,
)
from episignal_backend.ingestion.dedupe import DedupeThresholds, run_dedupe
from episignal_backend.ingestion.discovery import run_discovery, run_retry
from episignal_backend.ingestion.ecdc_epi import EcdcEpiConnector
from episignal_backend.ingestion.gdelt.api import GdeltDocClient
from episignal_backend.ingestion.gdelt.article import ArticleFetcher
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.pipeline import run_ingestion
from episignal_backend.ingestion.pregroup import group_signals
from episignal_backend.ingestion.pregroup_store import SqlAlchemyPreGroupStore
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
        # Retry first: a stub is a page already known to be wanted, so it has a
        # better claim on the run budget than an article not yet seen.
        retried = run_retry(
            repository,
            connector,
            max_attempts=settings.gdelt_max_retrieval_attempts,
            batch_size=settings.gdelt_retry_batch_size,
        )
        discovered = run_discovery(
            repository,
            connector,
            now=window.end,
            window_minutes=window.minutes,
            max_articles=settings.gdelt_max_articles_per_run,
        )
    return {
        "retried": retried.attempted,
        "promoted": retried.promoted,
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


def _pregroup() -> Mapping[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)

    if not settings.pregroup_enabled:
        with session_scope() as session:
            resolved, expired = SqlAlchemyPreGroupStore(session).resolve_and_expire(
                expiry_hours=settings.pregroup_expiry_hours,
                now=now,
            )
            session.commit()
        return {
            "resolved": resolved,
            "expired": expired,
        }

    with session_scope() as session:
        store = SqlAlchemyPreGroupStore(session)
        resolved, expired = store.resolve_and_expire(
            expiry_hours=settings.pregroup_expiry_hours, now=now
        )
        candidates = store.candidates(limit=settings.pregroup_batch_size)
        groups = group_signals(candidates, window_days=settings.pregroup_window_days)
        written = store.write_groups(groups, window_days=settings.pregroup_window_days, now=now)
        session.commit()

    deferred = sum(len(group.deferred) for group in groups)
    return {
        "examined": len(candidates),
        "groups": written,
        "deferred": deferred,
        "resolved": resolved,
        "expired": expired,
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


def _embed() -> Mapping[str, int]:
    settings = get_settings()
    provider = LocalBgeM3Provider(
        model_name=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
    )
    with session_scope() as session:
        result = run_embedding(
            SqlAlchemyAiRepository(session),
            provider,
            batch_size=settings.embedding_batch_size,
        )
    return {
        "examined": result.examined,
        "embedded": result.embedded,
        "failed": result.failed,
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
        "review": extracted.reviewed,
        "unavailable": extracted.unavailable,
        "requests": extracted.requests,
    }


def _geocode() -> Mapping[str, int]:
    settings = get_settings()
    limit = min(settings.geocode_batch_size, settings.geocode_max_signals_per_run)
    with session_scope() as session:
        # Same wiring as geocode_runner: the cache is a local table and is
        # always in play; the live client exists only when the operator has
        # enabled Nominatim, and otherwise the stage never reaches the network.
        result = run_geocoding(
            SqlAlchemyGeocodeRepository(session),
            SqlAlchemyGazetteerRepository(session),
            limit=limit,
            source=settings.gazetteer_source,
            stale=False,
            cache=SqlAlchemyGeocodeCacheRepository(session),
            nominatim=(
                NominatimClient(
                    base_url=settings.nominatim_url,
                    user_agent=settings.nominatim_user_agent,
                    timeout=settings.nominatim_timeout_seconds,
                )
                if settings.nominatim_enabled
                else None
            ),
        )
    return {
        "examined": result.examined,
        "located": result.located,
        "unresolved": result.unresolved,
        "locations": result.locations,
    }


def _match() -> Mapping[str, int]:
    settings = get_settings()
    with session_scope() as session:
        event_repository = SqlAlchemyEventRepository(session)
        specs = list(SqlAlchemyAiRepository(session).models())
        # The delta pass is enrichment: without a provider key the assembly
        # still runs, it simply never records what changed.
        wiring = configure_delta(settings, specs)
        judge = configure_judge(settings, specs)
        summary = run_event_assembly(
            event_repository,
            limit=settings.event_match_batch_size,
            stale=False,
            cluster_window_days=settings.event_cluster_window_days,
            cluster_distance_km=settings.event_cluster_distance_km,
            match_threshold=settings.event_match_threshold,
            review_threshold=settings.event_match_review_threshold,
            match_recency_days=settings.event_match_recency_days,
            match_distance_km=settings.event_match_distance_km,
            candidate_lookback_days=settings.event_lookback_days,
            candidate_limit=settings.event_candidate_limit,
            delta_model=wiring.model,
            delta_spec=wiring.spec,
            followup_window_days=wiring.window_days,
            judge_model=judge.model,
            judge_spec=judge.spec,
        )
    return {
        "seen": summary.signals_seen,
        "clusters": summary.clusters_built,
        "created": summary.events_created,
        "attached": summary.signals_attached,
        "refused": summary.signals_refused,
        "unclusterable": summary.unclusterable,
        "deltas": summary.deltas_applied,
        "judged": summary.ambiguous_judged,
        "judge_attached": summary.ambiguous_attached,
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
            result = run_summary(
                wiring.model,
                wiring.spec,
                event=event,
                sources=sources,
            )
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
                    model_id=wiring.spec.model_id,
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
        StageName.INGEST_ECDC: lambda: _ingest(EcdcEpiConnector()),
        StageName.DISCOVER: lambda: _discover(window),
        StageName.RETRIEVE: _retrieve,
        StageName.DEDUPE: _dedupe,
        StageName.TRIAGE: _triage,
        StageName.EMBED: _embed,
        StageName.PREGROUP: _pregroup,
        StageName.EXTRACT: _extract,
        StageName.GEOCODE: _geocode,
        StageName.MATCH: _match,
        StageName.SUMMARIZE: _summarize,
    }
