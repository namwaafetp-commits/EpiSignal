from decimal import Decimal
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

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    gemini_api_key: SecretStr | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    review_admin_token: SecretStr | None = None

    ai_signal_batch_limit: int = Field(default=100, ge=1, le=5000)
    ai_batch_size: int = Field(default=20, ge=1, le=200)
    # The binding guard under a free ladder: free endpoints are rated per
    # request and per day, so a run that respects a dollar cap can still burn a
    # day's quota in a minute.
    ai_max_requests_per_run: int = Field(default=200, ge=1, le=10000)
    ai_max_cost_usd_per_run: Decimal = Field(default=Decimal("0.50"), ge=0)
    ai_min_confidence: float = Field(default=0.60, ge=0.0, le=1.0)
    ai_max_input_characters: int = Field(default=12000, ge=500, le=200000)
    ai_request_delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    ai_request_timeout_seconds: float = Field(default=60.0, ge=1.0, le=300.0)
    ai_max_attempts_per_tier: int = Field(default=3, ge=1, le=10)
    ai_max_tier: int = Field(default=3, ge=1, le=3)

    geocode_batch_size: int = Field(default=200, ge=1, le=5000)
    geocode_max_signals_per_run: int = Field(default=2000, ge=1, le=100000)
    # Stamped onto every row this run writes, and the value `--stale` compares
    # against. Bump it whenever the seed artifact is regenerated, or a refreshed
    # gazetteer reaches only signals processed after it.
    gazetteer_source: str = Field(default="geonames-2026-08-27", min_length=1)

    # Nominatim, the OpenStreetMap place search consulted only when the local
    # gazetteer has no candidate at all for a name. Off by default: the
    # scheduled pipeline never makes a network call an operator has not
    # switched on, and every successful answer is cached so it is paid for once.
    nominatim_enabled: bool = False
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    nominatim_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    # Nominatim asks that requests carry an identifying User-Agent.
    nominatim_user_agent: str = "EpiSignal/0.1 (episignal backend)"

    event_cluster_window_days: int = Field(default=7, ge=1, le=365)
    event_cluster_distance_km: float = Field(default=50.0, ge=0.0, le=1000.0)
    event_match_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    event_match_recency_days: float = Field(default=90.0, ge=1.0, le=3650.0)
    event_match_distance_km: float = Field(default=50.0, ge=0.0, le=1000.0)
    event_match_batch_size: int = Field(default=100, ge=1, le=5000)
    event_match_stale: bool = False
    # How recent an event's latest report must be for a follow-up attach to
    # run the delta pass. Ten days: the operator's window for stateful
    # follow-up, kept configurable like every other matching bound.
    event_followup_window_days: float = Field(default=10.0, ge=0.0, le=3650.0)

    # Seven days. Bounds the query issued after a long gap: a laptop closed for
    # a month asks for a week, not a month GDELT would refuse.
    pipeline_catch_up_max_minutes: int = Field(default=10080, ge=1, le=43200)
    pipeline_chain: Literal["daily"] = "daily"

    # Pre-group stage. Default off: the design ships it dark and lets the
    # trailing-spend measurement decide whether it is ever enabled.
    pregroup_enabled: bool = False
    pregroup_window_days: int = Field(default=1, ge=1, le=2)
    pregroup_expiry_hours: int = Field(default=72, ge=1, le=720)
    pregroup_batch_size: int = Field(default=200, ge=1, le=5000)

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

    @field_validator("gazetteer_source")
    @classmethod
    def gazetteer_source_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("EPISIGNAL_GAZETTEER_SOURCE must name the gazetteer in use")
        return value

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

    @model_validator(mode="after")
    def catch_up_covers_the_query_window(self) -> "Settings":
        if self.pipeline_catch_up_max_minutes < self.gdelt_query_window_minutes:
            raise ValueError(
                "EPISIGNAL_PIPELINE_CATCH_UP_MAX_MINUTES must cover "
                "EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES"
            )
        return self

    @model_validator(mode="after")
    def batch_fits_the_run(self) -> "Settings":
        # A batch larger than the run's queue would make the guards unreadable:
        # the run would appear to stop early when it had simply asked for more
        # signals than it selected.
        if self.ai_batch_size > self.ai_signal_batch_limit:
            raise ValueError(
                "EPISIGNAL_AI_BATCH_SIZE must not exceed EPISIGNAL_AI_SIGNAL_BATCH_LIMIT"
            )
        return self

    @model_validator(mode="after")
    def geocode_batch_fits_the_run(self) -> "Settings":
        if self.geocode_batch_size > self.geocode_max_signals_per_run:
            raise ValueError(
                "EPISIGNAL_GEOCODE_BATCH_SIZE must not exceed EPISIGNAL_GEOCODE_MAX_SIGNALS_PER_RUN"
            )
        return self

    @property
    def sqlalchemy_database_url(self) -> str:
        return normalize_database_url(self.database_url.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
