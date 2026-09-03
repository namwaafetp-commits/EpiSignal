"""PostgreSQL integration coverage for exact disease vocabulary matching."""

import os
from uuid import uuid4

import pytest
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import normalize_database_url
from episignal_backend.models import Disease
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def test_db_url() -> str:
    raw_url = os.environ.get("EPISIGNAL_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("EPISIGNAL_TEST_DATABASE_URL not configured")
    production_url = os.environ.get("EPISIGNAL_DATABASE_URL")
    if production_url and raw_url == production_url:
        pytest.fail("EPISIGNAL_TEST_DATABASE_URL must not equal EPISIGNAL_DATABASE_URL")
    return normalize_database_url(raw_url)


def test_resolve_disease_matches_reviewed_names_exactly_case_insensitively(
    test_db_url: str,
) -> None:
    engine = create_engine(test_db_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                ebola_id = uuid4()
                west_nile_id = uuid4()
                meningococcal_id = uuid4()
                session = Session(bind=connection)
                session.add_all(
                    [
                        Disease(
                            id=ebola_id,
                            canonical_name="Ebola   virus disease",
                            slug="resolver-test-ebola-virus-disease",
                            synonyms=["Ebola"],
                        ),
                        Disease(
                            id=west_nile_id,
                            canonical_name="West Nile virus disease",
                            slug="resolver-test-west-nile-virus-disease",
                            synonyms=["West Nile virus infection"],
                        ),
                        Disease(
                            id=meningococcal_id,
                            canonical_name="Meningococcal disease",
                            slug="resolver-test-meningococcal-disease",
                            synonyms=["  meningococcal   meningitis  "],
                        ),
                    ]
                )
                session.flush()
                repository = SqlAlchemyAiRepository(session)

                assert repository.resolve_disease("Ebola") == ebola_id
                assert repository.resolve_disease("ebola") == ebola_id
                assert repository.resolve_disease("EBOLA") == ebola_id
                assert repository.resolve_disease(" Ebola   virus disease ") == ebola_id
                assert repository.resolve_disease("EBOLA VIRUS DISEASE") == ebola_id
                assert repository.resolve_disease("RESOLVER-TEST-EBOLA-VIRUS-DISEASE") == ebola_id

                assert repository.resolve_disease("West Nile virus infection") == west_nile_id
                assert repository.resolve_disease("west   nile virus infection") == west_nile_id
                assert repository.resolve_disease("WEST NILE VIRUS INFECTION") == west_nile_id
                assert repository.resolve_disease("Meningococcal Meningitis") == meningococcal_id

                assert repository.resolve_disease("rabies") is None
                assert repository.resolve_disease("West Nile virus") is None
                assert repository.resolve_disease("H5 bird flu") is None
                assert repository.resolve_disease("Chikungunya and Dengue") is None
                assert repository.resolve_disease("bola") is None
            finally:
                session.close()
                transaction.rollback()
    finally:
        engine.dispose()
