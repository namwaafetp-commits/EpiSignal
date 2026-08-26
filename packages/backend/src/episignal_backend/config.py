from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BeforeValidator, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
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
    cors_origins: Annotated[tuple[str, ...], BeforeValidator(parse_origins)] = (
        "http://localhost:3000",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

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

    @property
    def sqlalchemy_database_url(self) -> str:
        return normalize_database_url(self.database_url.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
