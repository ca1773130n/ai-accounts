from typing import Any, Protocol, runtime_checkable

import msgspec

from ai_accounts_core.domain.principal import Principal


class RequestContext(msgspec.Struct, frozen=True, kw_only=True):
    method: str
    path: str
    headers: dict[str, str]
    query: dict[str, str] = {}
    extras: dict[str, Any] = {}


@runtime_checkable
class AuthProtocol(Protocol):
    async def authenticate(self, request: RequestContext) -> Principal | None: ...
