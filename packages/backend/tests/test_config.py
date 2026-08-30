import pytest
from episignal_backend.config import Settings, normalize_database_url
from pydantic import ValidationError


def test_normalizes_supabase_postgres_url_for_psycopg() -> None:
    assert normalize_database_url("postgresql://user:secret@host/db") == (
        "postgresql+psycopg://user:secret@host/db"
    )


def test_keeps_explicit_psycopg_url() -> None:
    url = "postgresql+psycopg://user:secret@host/db"
    assert normalize_database_url(url) == url


def test_rejects_non_postgresql_database_url() -> None:
    with pytest.raises(ValueError, match="EPISIGNAL_DATABASE_URL"):
        normalize_database_url("sqlite:///episignal.db")


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://",
        "postgresql://user@host/database",
        "postgresql://user:password@/database",
        "postgresql://user:password@host",
    ],
)
def test_rejects_incomplete_postgresql_database_url(value: str) -> None:
    with pytest.raises(ValueError, match="EPISIGNAL_DATABASE_URL"):
        normalize_database_url(value)


def test_settings_reject_non_postgresql_database_url_during_creation() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///episignal.db", _env_file=None)  # type: ignore[call-arg, arg-type]


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
        cors_origins="http://localhost:3000,https://episignal.example",  # type: ignore[arg-type]
        _env_file=None,
    )
    assert settings.cors_origins == (
        "http://localhost:3000",
        "https://episignal.example",
    )


def test_settings_reject_invalid_cors_origin() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
            cors_origins="not-a-url",  # type: ignore[arg-type]
            _env_file=None,
        )


def test_database_secret_is_not_exposed_by_repr() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
        _env_file=None,
    )
    assert "secret" not in repr(settings)


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_parse_comma_separated_cors_origins_from_an_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EPISIGNAL_DATABASE_URL=postgresql://user:secret@host/db\n"
        "EPISIGNAL_CORS_ORIGINS=http://localhost:3000,https://episignal.example\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.cors_origins == (
        "http://localhost:3000",
        "https://episignal.example",
    )


def test_settings_parse_comma_separated_cors_origins_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("EPISIGNAL_DATABASE_URL", "postgresql://user:secret@host/db")
    monkeypatch.setenv("EPISIGNAL_CORS_ORIGINS", "http://localhost:3000,https://episignal.example")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.cors_origins == (
        "http://localhost:3000",
        "https://episignal.example",
    )


def test_gdelt_settings_have_working_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "EPISIGNAL_DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/database"
    )
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.gdelt_poll_interval_minutes == 15
    assert settings.gdelt_query_window_minutes == 20
    assert settings.gdelt_max_articles_per_run == 200
    assert settings.gdelt_request_delay_seconds == 5.0
    assert settings.gdelt_article_delay_seconds == 1.0
    assert settings.gdelt_max_retrieval_attempts == 3
    assert settings.gdelt_retry_batch_size == 50


def test_the_query_window_must_cover_the_poll_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "EPISIGNAL_DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/database"
    )
    monkeypatch.setenv("EPISIGNAL_GDELT_POLL_INTERVAL_MINUTES", "30")
    monkeypatch.setenv("EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES", "20")
    # A window narrower than the interval opens a gap no later run ever revisits.
    with pytest.raises(ValidationError, match="(?i)window"):
        Settings(_env_file=None)  # type: ignore[call-arg]


DATABASE_URL = "postgresql://user:secret@host/db"


def test_stage0_defaults_are_strict() -> None:
    settings = Settings(database_url=DATABASE_URL, _env_file=None)  # type: ignore[call-arg, arg-type]

    assert settings.stage0_title_similarity == 0.90
    assert settings.stage0_body_similarity == 0.80
    assert settings.stage0_shingle_size == 5
    assert settings.stage0_candidate_window_hours == 72
    assert settings.stage0_batch_size == 200
    assert settings.stage0_near_exact_title_similarity == 92.0
    assert settings.stage0_near_exact_window_hours == 48


def test_a_similarity_threshold_above_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg, arg-type]
            database_url=DATABASE_URL,
            stage0_title_similarity=1.5,
            _env_file=None,
        )


@pytest.mark.parametrize("value", [-0.1, 100.1])
def test_a_near_exact_title_threshold_outside_zero_to_one_hundred_is_rejected(
    value: float,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url=DATABASE_URL,
            stage0_near_exact_title_similarity=value,
            _env_file=None,
        )


def build_settings(**overrides: str) -> Settings:
    values: dict[str, object] = {"database_url": DATABASE_URL, "_env_file": None}
    for k, v in overrides.items():
        key = k[len("EPISIGNAL_") :].lower() if k.startswith("EPISIGNAL_") else k
        values[key] = v
    return Settings(**values)  # type: ignore[arg-type]


def test_the_ai_defaults_describe_a_free_ladder() -> None:
    settings = build_settings()

    assert settings.ai_max_tier == 3
    assert settings.ai_batch_size == 20
    assert settings.ai_triage_batch_limit == 200
    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.embedding_provider == "local"
    assert settings.embedding_batch_size == 16
    assert settings.ai_max_requests_per_run == 200
    assert settings.ai_min_confidence == 0.60


def test_the_openrouter_key_is_absent_by_default() -> None:
    settings = build_settings()

    assert settings.openrouter_api_key is None


def test_the_openrouter_key_is_not_printed_by_repr() -> None:
    settings = build_settings(EPISIGNAL_OPENROUTER_API_KEY="sk-secret-value")

    assert "sk-secret-value" not in repr(settings)


def test_a_batch_larger_than_the_run_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_BATCH_SIZE="500", EPISIGNAL_AI_SIGNAL_BATCH_LIMIT="100")


def test_a_confidence_floor_outside_zero_to_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_MIN_CONFIDENCE="1.5")


def test_a_zero_request_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_MAX_REQUESTS_PER_RUN="0")


def test_a_negative_cost_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_MAX_COST_USD_PER_RUN="-1")


def test_a_tier_above_the_ladder_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_MAX_TIER="4")


def test_geocoding_defaults_are_set() -> None:
    settings = build_settings()
    assert settings.geocode_batch_size == 200
    assert settings.geocode_max_signals_per_run == 2000
    assert settings.gazetteer_source == "geonames-2026-08-27"


def test_nominatim_defaults_are_off() -> None:
    # The scheduled pipeline must never make a network call an operator has
    # not switched on, so the live geocoder ships dark.
    settings = build_settings()
    assert settings.nominatim_enabled is False
    assert settings.nominatim_url == "https://nominatim.openstreetmap.org"
    assert settings.nominatim_timeout_seconds == 10.0
    assert settings.nominatim_user_agent == "EpiSignal/0.1 (episignal backend)"


def test_the_geocoding_batch_must_fit_the_run() -> None:
    with pytest.raises(ValidationError):
        build_settings(
            EPISIGNAL_GEOCODE_BATCH_SIZE="500",
            EPISIGNAL_GEOCODE_MAX_SIGNALS_PER_RUN="100",
        )


def test_the_gazetteer_source_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_GAZETTEER_SOURCE="   ")


def test_event_matching_defaults_are_set() -> None:
    settings = build_settings()
    assert settings.event_cluster_window_days == 7
    assert settings.event_cluster_distance_km == 50.0
    assert settings.event_match_threshold == 0.75
    assert settings.event_match_recency_days == 90.0
    assert settings.event_match_distance_km == 50.0
    assert settings.event_match_batch_size == 100
    assert settings.event_match_stale is False
    assert settings.event_lookback_days == 7
    assert settings.event_candidate_limit == 20
    assert settings.event_match_review_threshold == 0.55
    assert settings.event_match_judge_batch_size == 20
    assert settings.resummary_new_article_count == 3
    assert settings.resummary_max_age_hours == 24
    assert settings.summary_max_sources == 6


def test_event_match_threshold_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_EVENT_MATCH_THRESHOLD="1.5")

    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_EVENT_MATCH_THRESHOLD="-0.1")


def test_event_match_review_threshold_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_EVENT_MATCH_REVIEW_THRESHOLD="1.5")

    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_EVENT_MATCH_REVIEW_THRESHOLD="-0.1")


def test_the_catch_up_clamp_defaults_to_seven_days() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
        _env_file=None,
    )

    assert settings.pipeline_catch_up_max_minutes == 10080


def test_the_default_chain_is_daily() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
        _env_file=None,
    )

    assert settings.pipeline_chain == "daily"


def test_a_catch_up_clamp_shorter_than_the_query_window_is_refused() -> None:
    # A clamp inside the window would make the very first run ask for less than
    # the window it was configured with, which no later run ever repairs.
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
            gdelt_query_window_minutes=1500,
            pipeline_catch_up_max_minutes=600,
            _env_file=None,
        )
