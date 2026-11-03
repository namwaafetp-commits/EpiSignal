"""PostgreSQL proof for the deployment-time AI roster transition."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from episignal_backend.ai.registry import model_for_purpose
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import Settings
from episignal_backend.db.types import AiPurpose
from episignal_backend.events.summarize import configure_summary
from episignal_backend.seeds import seed_database
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).parents[3]
ALEMBIC_INI = ROOT / "database" / "alembic.ini"
DEEPSEEK = "deepseek/deepseek-v4-flash-0731"
LEGACY_MISTRAL = "mistralai/mistral-small-3.2-24b-instruct"


@pytest.fixture
def test_db_url() -> str:
    url = os.environ.get("EPISIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("EPISIGNAL_TEST_DATABASE_URL not configured")
    main_url = os.environ.get("EPISIGNAL_DATABASE_URL")
    if main_url and url == main_url:
        pytest.fail("EPISIGNAL_TEST_DATABASE_URL must not equal EPISIGNAL_DATABASE_URL")
    return url


def _config(url: str) -> Config:
    config = Config(ALEMBIC_INI)
    config.set_main_option("sqlalchemy.url", url)
    return config


def _assert_final_roster(engine) -> None:
    with Session(engine) as session:
        specs = SqlAlchemyAiRepository(session).models()

    summary = model_for_purpose(specs, AiPurpose.EVENT_SUMMARY)
    assert summary.model_id == DEEPSEEK
    assert summary.provider.value == "openrouter"
    assert summary.purpose is AiPurpose.EVENT_SUMMARY

    settings = Settings(
        database_url="postgresql://user:secret@host/db",
        openrouter_api_key="test-openrouter-key",
        _env_file=None,
    )
    wiring = configure_summary(settings, list(specs))
    assert wiring.model is not None
    assert wiring.spec is not None
    assert wiring.spec.provider.value == "openrouter"
    assert wiring.spec.model_id == DEEPSEEK

    assert model_for_purpose(specs, AiPurpose.CLASSIFICATION).model_id == DEEPSEEK
    assert model_for_purpose(specs, AiPurpose.EXTRACTION).model_id == "google/gemini-3.1-flash-lite"


def test_fresh_migration_and_bootstrap_need_no_manual_roster_action(test_db_url: str) -> None:
    config = _config(test_db_url)
    engine = create_engine(test_db_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    # Normal bootstrap is safe to run after the migration and converges on the
    # same row instead of requiring a separate SQL/configuration step.
    with Session(engine) as session:
        seed_database(session)
        session.commit()

    _assert_final_roster(engine)


def test_existing_roster_is_upgraded_without_rewriting_summary_history(test_db_url: str) -> None:
    config = _config(test_db_url)
    engine = create_engine(test_db_url)
    command.downgrade(config, "base")
    command.upgrade(config, "20260911_0024")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ai_models (
                    tier, model_id, label, provider, purpose,
                    prompt_price_per_million, completion_price_per_million, active
                ) VALUES
                    (1, :deepseek, 'DeepSeek V4 Flash', 'openrouter',
                     'classification', 0.03, 0.10, true),
                    (1, :mistral, 'Mistral Small 3.2 24B', 'openrouter',
                     'event_summary', 0.00, 0.00, true)
                """
            ),
            {"deepseek": DEEPSEEK, "mistral": LEGACY_MISTRAL},
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        old_summary_count = connection.execute(
            text("SELECT count(*) FROM event_summaries")
        ).scalar_one()
        old_mistral_active = connection.execute(
            text("SELECT active FROM ai_models WHERE model_id = :model_id"),
            {"model_id": LEGACY_MISTRAL},
        ).scalar_one()
        assert old_summary_count == 0
        assert old_mistral_active is False

    _assert_final_roster(engine)
