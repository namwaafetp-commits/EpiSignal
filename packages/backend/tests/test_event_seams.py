import ast
from pathlib import Path

import pytest

EVENTS = Path(__file__).parents[1] / "src" / "episignal_backend" / "events"
PURE_MODULES = ("documents.py", "cluster.py", "match.py", "score.py", "protocol.py", "assemble.py")


def _imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


@pytest.mark.parametrize("name", PURE_MODULES)
def test_a_pure_module_imports_no_database_driver(name: str) -> None:
    imports = _imported_top_levels(EVENTS / name)
    assert "sqlalchemy" not in imports
    assert "geoalchemy2" not in imports


def test_no_module_in_events_touches_the_network() -> None:
    for path in EVENTS.glob("*.py"):
        imports = _imported_top_levels(path)
        assert "httpx" not in imports
        assert "requests" not in imports
        assert "urllib3" not in imports


def test_only_the_repository_imports_sqlalchemy() -> None:
    importers = {
        path.name for path in EVENTS.glob("*.py") if "sqlalchemy" in _imported_top_levels(path)
    }
    assert importers == {"repository.py"}
