import hmac
import os

from ai_accounts_core.domain.principal import Principal
from ai_accounts_core.protocols.auth import RequestContext

_PREFIX = "bearer "


class ApiKeyAuth:
    """Bearer-token auth against a single shared secret from the environment."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("ApiKeyAuth requires a non-empty token")
        self._token = token
        self._principal = Principal(
            id="api_key",
            display_name="API Key",
            scopes=frozenset({"*"}),
        )

    @classmethod
    def from_env(cls, env_var: str = "AI_ACCOUNTS_API_KEY") -> "ApiKeyAuth":
        token = os.environ.get(env_var, "")
        if not token:
            raise RuntimeError(
                f"{env_var} is not set; ApiKeyAuth cannot start. "
                "Set it to a non-empty secret or use NoAuth for development."
            )
        return cls(token)

    async def authenticate(self, request: RequestContext) -> Principal | None:
        header = request.headers.get("authorization") or request.headers.get("Authorization")
        if not header:
            return None
        if not header.lower().startswith(_PREFIX):
            return None
        presented = header[len(_PREFIX):]
        if not hmac.compare_digest(presented, self._token):
            return None
        return self._principal
