"""Tests for manual review authentication and admin token verification."""

from unittest.mock import patch
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from episignal_api.dependencies import verify_admin_token
from episignal_backend.config import Settings
from fastapi.security import HTTPAuthorizationCredentials


def test_verify_admin_token_succeeds_with_bearer_token() -> None:
    settings = Settings(
        database_url="postgresql://test:test@localhost/test",
        review_admin_token=SecretStr("super-secret-token"),
        _env_file=None,
    )
    with patch("episignal_api.dependencies.get_settings", return_value=settings):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="super-secret-token")
        principal = verify_admin_token(credentials=creds, x_admin_token=None)
        assert principal == "admin"


def test_verify_admin_token_succeeds_with_x_admin_token_header() -> None:
    settings = Settings(
        database_url="postgresql://test:test@localhost/test",
        review_admin_token=SecretStr("super-secret-token"),
        _env_file=None,
    )
    with patch("episignal_api.dependencies.get_settings", return_value=settings):
        principal = verify_admin_token(credentials=None, x_admin_token="super-secret-token")
        assert principal == "admin"


def test_verify_admin_token_rejects_invalid_token() -> None:
    settings = Settings(
        database_url="postgresql://test:test@localhost/test",
        review_admin_token=SecretStr("super-secret-token"),
        _env_file=None,
    )
    with patch("episignal_api.dependencies.get_settings", return_value=settings):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_token(credentials=creds, x_admin_token=None)
        assert exc_info.value.status_code == 401


def test_verify_admin_token_rejects_missing_token_when_configured() -> None:
    settings = Settings(
        database_url="postgresql://test:test@localhost/test",
        review_admin_token=SecretStr("super-secret-token"),
        _env_file=None,
    )
    with patch("episignal_api.dependencies.get_settings", return_value=settings):
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_token(credentials=None, x_admin_token=None)
        assert exc_info.value.status_code == 401


def test_verify_admin_token_fails_safe_in_production_without_configured_token() -> None:
    settings = Settings(
        database_url="postgresql://test:test@localhost/test",
        env="production",
        review_admin_token=None,
        _env_file=None,
    )
    with patch("episignal_api.dependencies.get_settings", return_value=settings):
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_token(credentials=None, x_admin_token=None)
        assert exc_info.value.status_code in (401, 503)
