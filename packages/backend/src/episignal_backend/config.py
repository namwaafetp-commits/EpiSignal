from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        normalized = value.replace("postgres://", "postgresql+psycopg://", 1)
    elif value.startswith("postgresql://"):
        normalized = value.replace("postgresql://", "postgresql+psycopg://", 1)
    elif value.startswith("postgresql+psycopg://"):
        normalized = value
    else:
        raise ValueError("EPISIGNAL_DATABASE_URL must use a PostgreSQL psycopg URL")

    try:
        url = make_url(normalized)
    except ArgumentError as error:
        raise ValueError("EPISIGNAL_DATABASE_URL is malformed") from error

    if not all((url.username, url.password, url.host, url.database)):
        raise ValueError("EPISIGNAL_DATABASE_URL requires credentials, host, and database")

    return normalized


def parse_origins(value: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EPISIGNAL_",
        env_file="apps/api/.env",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: SecretStr
    # NoDecode stops pydantic-settings from JSON-decoding this sequence field
    # before the validator runs, so a plain comma-separated .env value works.
    cors_origins: Annotated[tuple[str, ...], NoDecode, BeforeValidator(parse_origins)] = (
        "http://localhost:3000",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    gdelt_poll_interval_minutes: int = Field(default=15, ge=1, le=1440)
    gdelt_query_window_minutes: int = Field(default=20, ge=1, le=10080)
    gdelt_max_articles_per_run: int = Field(default=200, ge=1, le=5000)
    gdelt_request_delay_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
    gdelt_article_delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    gdelt_article_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    gdelt_max_retrieval_attempts: int = Field(default=3, ge=1, le=20)
    gdelt_retry_batch_size: int = Field(default=50, ge=0, le=1000)
    gdelt_user_agent: str = "EpiSignal/0.1 (+https://episignal.org)"

    # The two thresholds are configuration because they are the numbers most
    # likely to need tuning against real traffic, and because the architecture
    # requires matching thresholds to stay configurable rather than compiled in.
    stage0_title_similarity: float = Field(default=0.90, ge=0.0, le=1.0)
    stage0_body_similarity: float = Field(default=0.80, ge=0.0, le=1.0)
    stage0_shingle_size: int = Field(default=5, ge=1, le=20)
    stage0_candidate_window_hours: int = Field(default=72, ge=1, le=720)
    stage0_batch_size: int = Field(default=200, ge=1, le=5000)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        normalize_database_url(value.get_secret_value())
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("EPISIGNAL_CORS_ORIGINS must contain HTTP(S) origins")
        return values

    @model_validator(mode="after")
    def window_covers_the_interval(self) -> "Settings":
        # A window narrower than the polling interval leaves articles published
        # in the gap undiscovered by every run, which no retry ever repairs.
        if self.gdelt_query_window_minutes < self.gdelt_poll_interval_minutes:
            raise ValueError(
                "EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES must cover "
                "EPISIGNAL_GDELT_POLL_INTERVAL_MINUTES"
            )
        return self

    @property
    def sqlalchemy_database_url(self) -> str:
        return normalize_database_url(self.database_url.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
