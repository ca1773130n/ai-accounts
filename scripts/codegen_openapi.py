"""Dump the Litestar OpenAPI schema and run openapi-typescript.

Writes:
  packages/ts-core/src/client/openapi.json
  packages/ts-core/src/client/generated.ts

CI runs `just codegen && git diff --exit-code` to fail on any drift.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.backends import ClaudeBackend, OpenCodeBackend
from ai_accounts_core.testing import FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig

REPO = Path(__file__).resolve().parents[1]
JSON_OUT = REPO / "packages/ts-core/src/client/openapi.json"
TS_OUT = REPO / "packages/ts-core/src/client/generated.ts"


def _build_app():
    return create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(":memory:"),
            vault=FakeVault(),
            auth=NoAuth(),
            backends=(ClaudeBackend(), OpenCodeBackend()),
        )
    )


def main() -> None:
    app = _build_app()
    schema_obj = app.openapi_schema
    if schema_obj is None:
        raise RuntimeError("Litestar did not produce an OpenAPI schema")
    schema = schema_obj.to_schema()

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {JSON_OUT}")

    subprocess.run(
        ["pnpm", "exec", "openapi-typescript", str(JSON_OUT), "-o", str(TS_OUT)],
        check=True,
        cwd=REPO,
    )
    print(f"wrote {TS_OUT}")


if __name__ == "__main__":
    main()
