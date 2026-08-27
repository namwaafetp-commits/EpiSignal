from pathlib import Path

import pytest

GEOCODE = Path(__file__).parents[1] / "src" / "episignal_backend" / "geocode"
DECISION_MODULES = ("documents.py", "normalize.py", "resolve.py", "protocol.py", "locate.py")


@pytest.mark.parametrize("name", DECISION_MODULES)
def test_a_decision_module_imports_no_database_driver(name: str) -> None:
    source = (GEOCODE / name).read_text(encoding="utf-8")
    assert "sqlalchemy" not in source.lower()


def test_no_module_in_the_sub_project_touches_the_network() -> None:
    # There is no provider to call. A future network geocoder is an adapter
    # module, and this test is what makes adding one a deliberate act.
    for path in GEOCODE.glob("*.py"):
        assert "httpx" not in path.read_text(encoding="utf-8").lower()


def test_only_the_repository_imports_sqlalchemy() -> None:
    importers = {
        path.name
        for path in GEOCODE.glob("*.py")
        if "sqlalchemy" in path.read_text(encoding="utf-8").lower()
    }
    assert importers == {"repository.py"}


def test_the_ladder_never_reads_a_population() -> None:
    # The tie-break prohibition, enforced structurally rather than only by the
    # behavioural tests: `resolve.py` has no access to population at all,
    # because `Candidate` does not carry it.
    from episignal_backend.geocode.documents import Candidate

    assert "population" not in Candidate.model_fields
