"""Lazy engine and session factories.

The engine is created on first use so importing the package never reads
credentials or opens a socket. Parameters are hidden from logs because the
connection string carries the Supabase password.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from episignal_backend.config import get_settings

CONNECT_TIMEOUT_SECONDS = 5


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().sqlalchemy_database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
        hide_parameters=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def connection_scope() -> Iterator[Connection]:
    with get_engine().connect() as connection:
        yield connection


def enforce_read_only_transaction(session: Session) -> None:
    """Make current transaction read-only and fail closed if PostgreSQL disagrees."""
    session.execute(text("SET TRANSACTION READ ONLY"))
    read_only = session.execute(text("SHOW transaction_read_only")).scalar_one()
    if str(read_only).lower() != "on":
        raise RuntimeError(
            f"read-only transaction enforcement failed: transaction_read_only={read_only}"
        )


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
