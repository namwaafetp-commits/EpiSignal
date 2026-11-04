"""Security migration contract and opt-in disposable PostgreSQL role checks."""

import io
import os
from pathlib import Path

import episignal_backend.models  # noqa: F401
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from episignal_backend.config import normalize_database_url
from episignal_backend.db.base import Base
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[3]


def migration():
    config = Config(str(ROOT / "database/alembic.ini"))
    return ScriptDirectory.from_config(config).get_revision("20261104_0028").module


def test_every_application_table_is_closed_to_direct_client_access() -> None:
    module = migration()
    assert set(module.TABLES) == set(Base.metadata.tables) | {"alembic_version"}
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={
            "as_sql": True,
            "output_buffer": output,
        },
    )
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    for table in module.TABLES:
        assert f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY' in sql
        assert f'REVOKE ALL ON TABLE public."{table}" FROM PUBLIC, anon, authenticated' in sql
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public" in sql
    assert "ON SEQUENCES FROM PUBLIC, anon, authenticated" in sql


def test_application_rollback_cannot_reopen_anonymous_access() -> None:
    with pytest.raises(RuntimeError, match="security boundary"):
        migration().downgrade()


def test_migration_denies_client_roles_and_preserves_server_access_on_postgresql() -> None:
    raw_url = os.environ.get("EPISIGNAL_ACCESS_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Disposable local access-test database not configured")
    parsed = make_url(raw_url)
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database == "episignal_access_test"
    engine = create_engine(normalize_database_url(raw_url), connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                assert (
                    connection.exec_driver_sql("SHOW data_directory")
                    .scalar_one()
                    .startswith("/private/tmp/episignal-access-")
                )
                assert connection.exec_driver_sql("SELECT current_user").scalar_one() == "postgres"
                assert (
                    connection.exec_driver_sql(
                        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
                    ).scalar_one()
                    == 0
                )
                for role in ("anon", "authenticated", "service_role"):
                    connection.exec_driver_sql(
                        f"CREATE ROLE {role}" + (" BYPASSRLS" if role == "service_role" else "")
                    )
                for kind in ("TABLES", "SEQUENCES"):
                    connection.exec_driver_sql(
                        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
                        f"GRANT ALL ON {kind} TO PUBLIC, anon, authenticated, service_role"
                    )
                module = migration()
                for table in module.TABLES:
                    connection.exec_driver_sql(f'CREATE TABLE public."{table}" (id integer)')
                with Operations.context(MigrationContext.configure(connection)):
                    module.upgrade()
                    module.upgrade()
                assert connection.exec_driver_sql(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND rowsecurity"
                ).scalar_one() == len(module.TABLES)
                for role in ("anon", "authenticated"):
                    for table in module.TABLES:
                        assert not connection.execute(
                            text(
                                "SELECT has_table_privilege(:role, :table, "
                                "'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')"
                            ),
                            {"role": role, "table": f"public.{table}"},
                        ).scalar_one()
                    for statement in (
                        "SELECT * FROM public.signals",
                        "INSERT INTO public.signals VALUES (1)",
                        "UPDATE public.signals SET id=1",
                        "DELETE FROM public.signals",
                    ):
                        with pytest.raises(DBAPIError) as error, connection.begin_nested():
                            connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                            connection.exec_driver_sql(statement)
                        assert error.value.orig.sqlstate == "42501"
                connection.exec_driver_sql("INSERT INTO public.signals VALUES (1)")
                assert connection.exec_driver_sql("SELECT id FROM public.signals").scalar_one() == 1
                with connection.begin_nested():
                    connection.exec_driver_sql("SET LOCAL ROLE service_role")
                    assert (
                        connection.exec_driver_sql("SELECT id FROM public.signals").scalar_one()
                        == 1
                    )
                connection.exec_driver_sql("RESET ROLE")
                connection.exec_driver_sql("UPDATE public.signals SET id=2")
                assert connection.exec_driver_sql("SELECT id FROM public.signals").scalar_one() == 2
                connection.exec_driver_sql("DELETE FROM public.signals")
                assert (
                    connection.exec_driver_sql("SELECT count(*) FROM public.signals").scalar_one()
                    == 0
                )
                connection.exec_driver_sql("CREATE TABLE public.future_table (id serial)")
                for role in ("anon", "authenticated"):
                    assert not connection.execute(
                        text(
                            "SELECT has_table_privilege(:role,'public.future_table',"
                            "'SELECT,INSERT,UPDATE,DELETE')"
                        ),
                        {"role": role},
                    ).scalar_one()
                    assert not connection.execute(
                        text(
                            "SELECT has_sequence_privilege(:role,'public.future_table_id_seq',"
                            "'USAGE,SELECT,UPDATE')"
                        ),
                        {"role": role},
                    ).scalar_one()
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
