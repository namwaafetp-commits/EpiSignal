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
    settings = Settings()  # type: ignore[call-arg]
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
    with pytest.raises(ValidationError, match="window"):
        Settings()  # type: ignore[call-arg]


DATABASE_URL = "postgresql://user:secret@host/db"


def test_stage0_defaults_are_strict() -> None:
    settings = Settings(database_url=DATABASE_URL, _env_file=None)  # type: ignore[call-arg, arg-type]

    assert settings.stage0_title_similarity == 0.90
    assert settings.stage0_body_similarity == 0.80
    assert settings.stage0_shingle_size == 5
    assert settings.stage0_candidate_window_hours == 72
    assert settings.stage0_batch_size == 200


def test_a_similarity_threshold_above_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg, arg-type]
            database_url=DATABASE_URL,
            stage0_title_similarity=1.5,
            _env_file=None,
        )
