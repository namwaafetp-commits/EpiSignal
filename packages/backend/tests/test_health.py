from episignal_backend.health import DatabaseHealth, check_database


class HealthyConnection:
    def scalar(self, statement: object) -> object:
        sql = str(statement)
        return "3.5 USE_GEOS=1" if "postgis_full_version" in sql else 1


class BrokenConnection:
    def scalar(self, statement: object) -> object:
        raise TimeoutError("database unavailable")


def test_database_health_requires_postgis() -> None:
    assert check_database(HealthyConnection()) == DatabaseHealth(database="up", postgis="up")


def test_database_health_sanitizes_connection_failures() -> None:
    result = check_database(BrokenConnection())
    assert result.database == "down"
    assert result.postgis == "unknown"
    assert "unavailable" not in repr(result)
