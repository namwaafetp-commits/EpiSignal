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
