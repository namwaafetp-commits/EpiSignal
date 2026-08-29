"""PostgreSQL integration test for migration 0014 manual review cases."""

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).parents[3]
ALEMBIC_INI = ROOT / "database" / "alembic.ini"
QUARANTINE_UUID = UUID("852aa204-846d-4aa6-a256-82c187fdeaef")


@pytest.fixture
def test_db_url() -> str:
    url = os.environ.get("EPISIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("EPISIGNAL_TEST_DATABASE_URL not configured")
    main_url = os.environ.get("EPISIGNAL_DATABASE_URL")
    if main_url and url == main_url:
        pytest.fail(
            "EPISIGNAL_TEST_DATABASE_URL must not equal EPISIGNAL_DATABASE_URL to protect production data"
        )
    return url


def test_manual_review_migration_full_cycle(test_db_url: str) -> None:
    alembic_cfg = Config(ALEMBIC_INI)
    alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)

    engine = create_engine(test_db_url)

    # 1. Downgrade to base, then upgrade to 0013
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "20260829_0013")

    source_id = uuid4()
    model_id = uuid4()
    sig_quarantine = QUARANTINE_UUID
    sig_null_text = uuid4()
    sig_rejected_ai = uuid4()
    sig_missing_disease = uuid4()
    sig_legacy = uuid4()

    with Session(engine) as session:
        # Create test source
        session.execute(
            text(
                """
                INSERT INTO sources (id, name, base_url, feed_url, source_type, credibility_tier, active, created_at, updated_at)
                VALUES (:id, 'Test Source', 'https://test.source', 'https://test.source/feed', 'international_organization', 'official', true, now(), now())
                """
            ),
            {"id": source_id},
        )
        # Create test AI model
        session.execute(
            text(
                """
                INSERT INTO ai_models (id, name, provider, tier, model_id, prompt_price_per_million, completion_price_per_million, active, created_at, updated_at)
                VALUES (:id, 'Test Model', 'openrouter', 1, 'test/model', 0.1, 0.2, true, now(), now())
                """
            ),
            {"id": model_id},
        )
        # Insert 5 synthetic signals at needs_review
        # 1. Quarantine
        session.execute(
            text(
                """
                INSERT INTO signals (id, source_id, url, canonical_url, title, raw_text, content_hash, processing_status, discovered_via, first_seen_at, retrieval_attempts, created_at, updated_at)
                VALUES (:id, :source_id, 'https://test.source/1', 'https://test.source/1', 'Quarantine Sig', 'Some text', 'hash1', 'needs_review', 'direct', now(), 1, now(), now())
                """
            ),
            {"id": sig_quarantine, "source_id": source_id},
        )
        # 2. Null text
        session.execute(
            text(
                """
                INSERT INTO signals (id, source_id, url, canonical_url, title, raw_text, content_hash, processing_status, discovered_via, first_seen_at, retrieval_attempts, created_at, updated_at)
                VALUES (:id, :source_id, 'https://test.source/2', 'https://test.source/2', 'Null Text Sig', NULL, 'hash2', 'needs_review', 'direct', now(), 1, now(), now())
                """
            ),
            {"id": sig_null_text, "source_id": source_id},
        )
        # 3. Rejected extraction
        session.execute(
            text(
                """
                INSERT INTO signals (id, source_id, url, canonical_url, title, raw_text, content_hash, processing_status, discovered_via, first_seen_at, retrieval_attempts, created_at, updated_at)
                VALUES (:id, :source_id, 'https://test.source/3', 'https://test.source/3', 'Rejected AI Sig', 'Some article text', 'hash3', 'needs_review', 'direct', now(), 1, now(), now())
                """
            ),
            {"id": sig_rejected_ai, "source_id": source_id},
        )
        session.execute(
            text(
                """
                INSERT INTO ai_requests (id, model_id, tier, purpose, signal_id, batch_size, prompt_tokens, completion_tokens, latency_ms, http_status, outcome, rejection_reason, prompt_price_per_million, completion_price_per_million, cost_usd, requested_at, created_at, updated_at)
                VALUES (gen_random_uuid(), :model_id, 1, 'extraction', :signal_id, 1, 10, 10, 100, 200, 'rejected', 'schema_invalid', 0.1, 0.2, 0.0001, now(), now(), now())
                """
            ),
            {"model_id": model_id, "signal_id": sig_rejected_ai},
        )
        # 4. Accepted extraction with missing disease_id
        session.execute(
            text(
                """
                INSERT INTO signals (id, source_id, url, canonical_url, title, raw_text, content_hash, processing_status, ai_extraction, disease_id, discovered_via, first_seen_at, retrieval_attempts, created_at, updated_at)
                VALUES (:id, :source_id, 'https://test.source/4', 'https://test.source/4', 'Missing Disease Sig', 'Some text', 'hash4', 'needs_review', '{"disease_text": "Unknown"}', NULL, 'direct', now(), 1, now(), now())
                """
            ),
            {"id": sig_missing_disease, "source_id": source_id},
        )
        # 5. Legacy fallback
        session.execute(
            text(
                """
                INSERT INTO signals (id, source_id, url, canonical_url, title, raw_text, content_hash, processing_status, discovered_via, first_seen_at, retrieval_attempts, created_at, updated_at)
                VALUES (:id, :source_id, 'https://test.source/5', 'https://test.source/5', 'Legacy Sig', 'Some text', 'hash5', 'needs_review', 'direct', now(), 1, now(), now())
                """
            ),
            {"id": sig_legacy, "source_id": source_id},
        )
        session.commit()

    # 2. Upgrade to 0014
    command.upgrade(alembic_cfg, "20260829_0014")

    # 3. Verify cases and reasons
    with Session(engine) as session:
        cases = session.execute(
            text(
                """
                SELECT id, signal_id, reason, status FROM signal_review_cases ORDER BY opened_at, id
                """
            )
        ).mappings().all()
        assert len(cases) == 5
        case_map = {row["signal_id"]: row for row in cases}

        assert case_map[sig_quarantine]["reason"] == "content_integrity"
        assert case_map[sig_null_text]["reason"] == "retrieval_failed"
        assert case_map[sig_rejected_ai]["reason"] == "extraction_rejected"
        assert case_map[sig_missing_disease]["reason"] == "disease_unresolved"
        assert case_map[sig_legacy]["reason"] == "legacy_unclassified"
        for row in cases:
            assert row["status"] == "open"

        # Verify signals are unchanged
        signals = session.execute(
            text("SELECT id, title, raw_text, content_hash, processing_status FROM signals")
        ).mappings().all()
        assert len(signals) == 5
        for sig in signals:
            assert sig["processing_status"] == "needs_review"

        initial_case_ids = {row["id"] for row in cases}

        # 4. Re-run the idempotent backfill query
        session.execute(
            text(
                """
                INSERT INTO signal_review_cases (
                    id,
                    signal_id,
                    reason,
                    status,
                    opened_at,
                    created_at,
                    updated_at
                )
                SELECT
                    gen_random_uuid(),
                    s.id,
                    CASE
                        WHEN s.id = '852aa204-846d-4aa6-a256-82c187fdeaef'::uuid THEN 'content_integrity'
                        WHEN s.raw_text IS NULL OR trim(s.raw_text) = '' THEN 'retrieval_failed'
                        WHEN s.ai_extraction IS NULL AND EXISTS (
                            SELECT 1 FROM ai_requests r WHERE r.signal_id = s.id AND r.outcome = 'rejected'
                        ) THEN 'extraction_rejected'
                        WHEN s.ai_extraction IS NOT NULL AND s.disease_id IS NULL THEN 'disease_unresolved'
                        ELSE 'legacy_unclassified'
                    END,
                    'open',
                    COALESCE(s.first_seen_at, s.created_at, now()),
                    now(),
                    now()
                FROM signals s
                WHERE s.processing_status = 'needs_review'
                ON CONFLICT (signal_id) WHERE status = 'open' DO NOTHING
                """
            )
        )
        session.commit()

        cases_after = session.execute(
            text("SELECT id FROM signal_review_cases")
        ).scalars().all()
        assert set(cases_after) == initial_case_ids

    # 5. Verify guarded downgrade refuses when data exists
    with pytest.raises(Exception) as exc_info:
        command.downgrade(alembic_cfg, "20260829_0013")
    assert "Cannot downgrade manual review schema after review data exists" in str(
        exc_info.value
    )

    # 6. Clean up
    with Session(engine) as session:
        session.execute(text("DELETE FROM signal_review_candidates"))
        session.execute(text("DELETE FROM signal_review_cases"))
        session.execute(text("DELETE FROM ai_requests"))
        session.execute(text("DELETE FROM signals"))
        session.execute(text("DELETE FROM ai_models"))
        session.execute(text("DELETE FROM sources"))
        session.commit()

    # Now empty downgrade should succeed
    command.downgrade(alembic_cfg, "20260829_0013")
    command.downgrade(alembic_cfg, "base")
