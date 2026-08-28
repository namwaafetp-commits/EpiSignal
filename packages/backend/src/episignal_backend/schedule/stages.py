"""Each stage, as the chain calls it.

Every function here calls the same domain function the matching runner calls.
The runners' own `main` and `_run` parse argv, print, and return exit codes,
none of which belong inside a chain.

Each stage opens its own session. That is deliberate: a stage that fails must
not roll back the stages that already succeeded, and the advisory lock is held
on a different connection for the whole run.
"""

from collections.abc import Mapping

from episignal_backend.ai.classify import run_classification
from episignal_backend.ai.extract import run_extraction
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.events.assemble import run_event_assembly
from episignal_backend.events.repository import SqlAlchemyEventRepository
from episignal_backend.geocode.locate import run_geocoding
from episignal_backend.geocode.repository import (
    SqlAlchemyGazetteerRepository,
    SqlAlchemyGeocodeRepository,
)
from episignal_backend.ingestion.dedupe import DedupeThresholds, run_dedupe
from episignal_backend.ingestion.discovery import run_discovery, run_retry
from episignal_backend.ingestion.ecdc_epi import EcdcEpiConnector
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
from episignal_backend.ingestion.who_don import WhoDonConnector
from episignal_backend.schedule.documents import DiscoveryWindow, StageName
from episignal_backend.schedule.run import StageRunner


def _ingest(connector: SourceConnector) -> Mapping[str, int]:
    with session_scope() as session:
        result = run_ingestion(
            SqlAlchemySignalRepository(session), connector, since=None
        )
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


def _dedupe() -> Mapping[str, int]:
    settings = get_settings()
    with session_scope() as session:
        result = run_dedupe(
            SqlAlchemyDedupeRepository(session),
            thresholds=DedupeThresholds(
                title=settings.stage0_title_similarity,
                body=settings.stage0_body_similarity,
                shingle_size=settings.stage0_shingle_size,
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


def _extract() -> Mapping[str, int]:
    settings = get_settings()
    if settings.openrouter_api_key is None:
        raise RuntimeError("EPISIGNAL_OPENROUTER_API_KEY is not set")

    model = OpenRouterChatModel(
        settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout_seconds=settings.ai_request_timeout_seconds,
        max_attempts=settings.ai_max_attempts_per_tier,
    )
    guards = Guards(
        max_requests=settings.ai_max_requests_per_run,
        max_cost_usd=settings.ai_max_cost_usd_per_run,
    )

    with session_scope() as session:
        repository = SqlAlchemyAiRepository(session)
        classified = run_classification(
            repository,
            model,
            guards=guards,
            batch_size=settings.ai_batch_size,
            limit=settings.ai_signal_batch_limit,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
        )
        extracted = run_extraction(
            repository,
            model,
            guards=guards,
            limit=settings.ai_signal_batch_limit,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
            min_confidence=settings.ai_min_confidence,
        )
    return {
        "classified": classified.examined,
        "relevant": classified.relevant,
        "irrelevant": classified.irrelevant,
        "extracted": extracted.extracted,
        "review": classified.reviewed + extracted.reviewed,
        "unavailable": classified.unavailable + extracted.unavailable,
        "requests": classified.requests + extracted.requests,
    }


def _geocode() -> Mapping[str, int]:
    settings = get_settings()
    limit = min(settings.geocode_batch_size, settings.geocode_max_signals_per_run)
    with session_scope() as session:
        result = run_geocoding(
            SqlAlchemyGeocodeRepository(session),
            SqlAlchemyGazetteerRepository(session),
            limit=limit,
            source=settings.gazetteer_source,
            stale=False,
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
        summary = run_event_assembly(
            SqlAlchemyEventRepository(session),
            limit=settings.event_match_batch_size,
            stale=False,
            cluster_window_days=settings.event_cluster_window_days,
            cluster_distance_km=settings.event_cluster_distance_km,
            match_threshold=settings.event_match_threshold,
            match_recency_days=settings.event_match_recency_days,
            match_distance_km=settings.event_match_distance_km,
        )
    return {
        "seen": summary.signals_seen,
        "clusters": summary.clusters_built,
        "created": summary.events_created,
        "attached": summary.signals_attached,
        "refused": summary.signals_refused,
        "unclusterable": summary.unclusterable,
    }


def build_stage_runners(*, window: DiscoveryWindow) -> dict[StageName, StageRunner]:
    """Map each stage to a callable. Nothing here runs until the chain calls it."""
    return {
        StageName.INGEST_WHO: lambda: _ingest(WhoDonConnector()),
        StageName.INGEST_ECDC: lambda: _ingest(EcdcEpiConnector()),
        StageName.DISCOVER: lambda: _discover(window),
        StageName.DEDUPE: _dedupe,
        StageName.EXTRACT: _extract,
        StageName.GEOCODE: _geocode,
        StageName.MATCH: _match,
    }
