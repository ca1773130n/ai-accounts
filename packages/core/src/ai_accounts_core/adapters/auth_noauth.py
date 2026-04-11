import logging

from ai_accounts_core.domain.principal import Principal
from ai_accounts_core.protocols.auth import RequestContext

log = logging.getLogger(__name__)


class NoAuth:
    """Dev-only auth provider that accepts every request as the 'local' principal.

    NEVER use this in production. The Litestar production-mode guard refuses to
    start with NoAuth configured.
    """

    _LOCAL_PRINCIPAL = Principal(
        id="local",
        display_name="Local Dev",
        scopes=frozenset({"*"}),
    )

    def __init__(self) -> None:
        log.warning(
            "ai-accounts: using NoAuth — ALL requests authenticated as 'local'. "
            "DO NOT use outside development."
        )

    async def authenticate(self, request: RequestContext) -> Principal | None:
        return self._LOCAL_PRINCIPAL
