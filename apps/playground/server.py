"""Run the ai-accounts playground server.

Listens on 127.0.0.1:20000. The Vite dev server proxies /api/* to this port.
"""

from __future__ import annotations

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.backends import ClaudeBackend, OpenCodeBackend
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig

app = create_app(
    AiAccountsConfig(
        env="development",
        storage=SqliteStorage("./playground.db"),
        vault=EnvKeyVault.from_env(env="development"),
        auth=NoAuth(),
        backends=(ClaudeBackend(), OpenCodeBackend()),
    )
)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=20000)


if __name__ == "__main__":
    main()
