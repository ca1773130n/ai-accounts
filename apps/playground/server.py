"""Run the ai-accounts playground server.

Default: listens on ``127.0.0.1:30000``. The Vite dev server proxies
``/api/*`` to this port.

Override via env:

* ``AIA_HOST=0.0.0.0`` — bind to all interfaces (e.g. when running behind
  vite's network proxy on a remote machine).
* ``AIA_PORT=6173`` — change the listen port.

The vite proxy target in ``vite.config.ts`` must match ``AIA_PORT``.
"""

from __future__ import annotations

import os
from pathlib import Path

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.backends import (
    ClaudeBackend,
    CodexBackend,
    GeminiBackend,
    OpenCodeBackend,
)
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig

app = create_app(
    AiAccountsConfig(
        env="development",
        storage=SqliteStorage("./playground.db"),
        vault=EnvKeyVault.from_env(env="development"),
        auth=NoAuth(),
        backends=(
            ClaudeBackend(),
            OpenCodeBackend(),
            GeminiBackend(),
            CodexBackend(),
        ),
        backend_dirs_path=Path("./backend_dirs"),
    )
)


def main() -> None:
    import uvicorn

    host = os.environ.get("AIA_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("AIA_PORT", "30000"))
    except ValueError:
        raise SystemExit(
            f"AIA_PORT must be an integer, got {os.environ['AIA_PORT']!r}"
        ) from None
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
