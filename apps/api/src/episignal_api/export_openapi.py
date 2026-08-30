"""Deterministic OpenAPI export for `pnpm contracts:generate`.

The placeholder connection string only satisfies validation; nothing here reads
`apps/api/.env`, imports the production entry point, or contacts a database, so
the contract can be regenerated and diffed in any environment.
"""

import json
from pathlib import Path

from episignal_backend.config import Settings
from pydantic import SecretStr

from episignal_api.factory import create_app

CONTRACT_PATH = Path(__file__).parents[4] / "packages" / "contracts" / "openapi.json"
PLACEHOLDER_DATABASE_URL = "postgresql://openapi:openapi@localhost/openapi"


def build_schema() -> dict[str, object]:
    settings = Settings(
        database_url=SecretStr(PLACEHOLDER_DATABASE_URL),
        _env_file=None,  # type: ignore[call-arg]
    )
    return create_app(settings).openapi()


def main() -> int:
    document = json.dumps(build_schema(), indent=2, sort_keys=True)
    CONTRACT_PATH.write_text(f"{document}\n", encoding="utf-8")
    print(f"wrote {CONTRACT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
