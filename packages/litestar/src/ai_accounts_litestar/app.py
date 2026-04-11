from typing import Any

from litestar import Litestar, get
from litestar.config.cors import CORSConfig
from litestar.di import Provide

from ai_accounts_core import __version__ as core_version
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import ServiceError

from .config import AiAccountsConfig
from .errors import service_error_handler
from .routes.backends import BackendsController


@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    return {"status": "ok", "version": core_version}


def _enforce_production_guards(config: AiAccountsConfig) -> None:
    if config.env != "production":
        return
    violations: list[str] = []

    vault_cls = type(config.vault).__name__
    if "Fake" in vault_cls:
        violations.append(
            f"vault is a test fake ({vault_cls}); use EnvKeyVault or a KMS adapter"
        )

    if isinstance(config.auth, NoAuth):
        violations.append("auth is NoAuth; use ApiKeyAuth or an OIDC adapter")

    if "*" in config.cors_origins:
        violations.append("cors_origins contains wildcard '*'; name explicit origins")

    if not config.cors_origins:
        violations.append("cors_origins is empty in production")

    if violations:
        raise RuntimeError(
            "ai-accounts refuses to start in production mode:\n  - "
            + "\n  - ".join(violations)
        )


def create_app(config: AiAccountsConfig) -> Litestar:
    _enforce_production_guards(config)

    impls = {b.kind: b for b in config.backends}
    account_service = AccountService(
        storage=config.storage,
        vault=config.vault,
        backends=impls,
        isolation_base_dir=config.backend_dirs_path,
    )

    def _provide_config() -> AiAccountsConfig:
        return config

    def _provide_account_service() -> AccountService:
        return account_service

    dependencies: dict[str, Any] = {
        "config": Provide(_provide_config, sync_to_thread=False),
        "account_service": Provide(_provide_account_service, sync_to_thread=False),
    }

    cors_config = (
        CORSConfig(allow_origins=list(config.cors_origins)) if config.cors_origins else None
    )

    async def _startup(_app: Litestar) -> None:
        await config.storage.migrate()

    return Litestar(
        route_handlers=[health, BackendsController],
        dependencies=dependencies,
        cors_config=cors_config,
        exception_handlers={ServiceError: service_error_handler},
        on_startup=[_startup],
        debug=config.env == "development",
    )
