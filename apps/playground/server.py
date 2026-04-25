"""Run the ai-accounts playground server.

Listens on 127.0.0.1:30000. The Vite dev server proxies /api/* to this port.
"""

from __future__ import annotations

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

    uvicorn.run(app, host="127.0.0.1", port=30000)


if __name__ == "__main__":
    main()
