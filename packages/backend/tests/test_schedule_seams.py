import ast
from pathlib import Path

import pytest

SCHEDULE = Path(__file__).parents[1] / "src" / "episignal_backend" / "schedule"
PURE_MODULES = ("documents.py", "chains.py", "window.py", "protocol.py", "run.py")


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
    imports = _imported_top_levels(SCHEDULE / name)
    assert "sqlalchemy" not in imports
    assert "geoalchemy2" not in imports


@pytest.mark.parametrize("name", PURE_MODULES)
def test_a_pure_module_touches_no_network(name: str) -> None:
    imports = _imported_top_levels(SCHEDULE / name)
    assert "httpx" not in imports
    assert "requests" not in imports


def test_only_the_repository_imports_sqlalchemy() -> None:
    importers = {
        path.name
        for path in SCHEDULE.glob("*.py")
        if "sqlalchemy" in _imported_top_levels(path)
    }
    assert importers == {"repository.py"}


def test_the_runner_prints_no_connection_string() -> None:
    runner = SCHEDULE.parent / "pipeline_runner.py"
    source = runner.read_text(encoding="utf-8")

    assert "database_url" not in source
    assert "get_secret_value" not in source
