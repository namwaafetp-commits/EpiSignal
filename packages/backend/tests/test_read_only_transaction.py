"""PostgreSQL-only proof that enforced read-only mode rejects writes."""

import os

import pytest
from episignal_backend.config import normalize_database_url
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


@pytest.fixture
def test_db_url() -> str:
    raw_url = os.environ.get("EPISIGNAL_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("EPISIGNAL_TEST_DATABASE_URL not configured")
    production_url = os.environ.get("EPISIGNAL_DATABASE_URL")
    if production_url and raw_url == production_url:
        pytest.fail("EPISIGNAL_TEST_DATABASE_URL must not equal EPISIGNAL_DATABASE_URL")
    return normalize_database_url(raw_url)


def test_postgresql_read_only_transaction_rejects_update(test_db_url: str) -> None:
    engine = create_engine(test_db_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('public.events')")).scalar_one()

            connection.execute(text("SET TRANSACTION READ ONLY"))
            assert connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on"

            with pytest.raises(DBAPIError, match="read-only"):
                connection.execute(text("UPDATE events SET headline = headline WHERE false"))

            connection.rollback()
    finally:
        engine.dispose()
