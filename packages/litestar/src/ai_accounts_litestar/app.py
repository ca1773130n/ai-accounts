import asyncio
import logging
from typing import Any

from litestar import Litestar, get
from litestar.config.cors import CORSConfig
from litestar.di import Provide

from ai_accounts_core import __version__ as core_version
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.login.registry import LoginSessionRegistry
from ai_accounts_core.metadata import BackendRegistry
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import ServiceError
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.onboarding import OnboardingService
from ai_accounts_core.services.pty import PtyService

from .config import AiAccountsConfig
from .errors import service_error_handler
from .routes.backends import BackendsController
from .routes.cliproxy import CliproxyController
from .routes.conversations import ConversationsController
from .routes.install import InstallController
from .routes.login import LoginController
from .routes.meta import MetaController
from .routes.models import ModelsController
from .routes.onboarding import OnboardingController
from .routes.pty_ws import PtyController, pty_websocket


logger = logging.getLogger(__name__)


async def _sweep_loop(registry: LoginSessionRegistry) -> None:
    """Periodically sweep expired login sessions."""
    while True:
        await asyncio.sleep(60)
        try:
            purged = await registry.sweep()
            if purged:
                logger.info("periodic sweep: removed %d expired sessions", purged)
        except Exception:
            logger.exception("periodic sweep failed")


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

    login_registry = LoginSessionRegistry(ttl_seconds=config.login_session_ttl_seconds)
    account_service = AccountService(
        storage=config.storage,
        vault=config.vault,
        backends=impls,
        isolation_base_dir=config.backend_dirs_path,
        login_registry=login_registry,
    )
    onboarding_service = OnboardingService(
        storage=config.storage,
        accounts=account_service,
        backend_kinds=tuple(impls.keys()),
    )
    chat_service = ChatService(
        account_service=account_service, storage=config.storage
    )
    pty_service = PtyService(
        account_service=account_service, storage=config.storage
    )

    backend_registry = BackendRegistry()
    for b in config.backends:
        backend_registry.register(b.metadata)

    def _provide_config() -> AiAccountsConfig:
        return config

    def _provide_account_service() -> AccountService:
        return account_service

    def _provide_onboarding_service() -> OnboardingService:
        return onboarding_service

    def _provide_backend_registry() -> BackendRegistry:
        return backend_registry

    def _provide_chat_service() -> ChatService:
        return chat_service

    def _provide_pty_service() -> PtyService:
        return pty_service

    dependencies: dict[str, Any] = {
        "config": Provide(_provide_config, sync_to_thread=False),
        "account_service": Provide(_provide_account_service, sync_to_thread=False),
        "onboarding_service": Provide(_provide_onboarding_service, sync_to_thread=False),
        "backend_registry": Provide(_provide_backend_registry, sync_to_thread=False),
        "chat_service": Provide(_provide_chat_service, sync_to_thread=False),
        "pty_service": Provide(_provide_pty_service, sync_to_thread=False),
    }

    cors_config = (
        CORSConfig(allow_origins=list(config.cors_origins)) if config.cors_origins else None
    )

    sweep_task_holder: list[asyncio.Task[None]] = []

    async def _startup(_app: Litestar) -> None:
        await config.storage.migrate()
        sweep_task_holder.append(asyncio.create_task(_sweep_loop(login_registry)))

    async def _shutdown(_app: Litestar) -> None:
        for task in sweep_task_holder:
            task.cancel()
        await login_registry.close()

    return Litestar(
        route_handlers=[
            health,
            BackendsController,
            CliproxyController,
            ConversationsController,
            InstallController,
            LoginController,
            MetaController,
            ModelsController,
            OnboardingController,
            PtyController,
            pty_websocket,
        ],
        dependencies=dependencies,
        cors_config=cors_config,
        exception_handlers={ServiceError: service_error_handler},
        on_startup=[_startup],
        on_shutdown=[_shutdown],
        debug=config.env == "development",
    )
