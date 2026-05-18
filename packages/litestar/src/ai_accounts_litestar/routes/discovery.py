"""Discovery route — auto-detect existing CLI logins.

GET  /api/v1/discovery               → list candidates with logged_in status
POST /api/v1/discovery/import        → create a backend from a candidate

The probe runs a real prompt against each candidate (claude -p hello, etc.)
so it costs upstream tokens — keep it user-triggered, not auto-on-load.
"""

from __future__ import annotations

import msgspec
from ai_accounts_core.services.accounts import AccountService
from litestar import Controller, get, post, status_codes

from ..dto import BackendDTO


class _DiscoveredItem(msgspec.Struct, kw_only=True):
    kind: str
    path: str
    suggested_name: str
    is_logged_in: bool
    error: str | None = None
    # Populated when this path is already represented as a backend row.
    # When set, the UI hides the Import button and the backend's status
    # has been synced to the probe result.
    backend_id: str | None = None


class _DiscoverResponse(msgspec.Struct, kw_only=True):
    items: list[_DiscoveredItem]


class _ImportRequest(msgspec.Struct, kw_only=True):
    kind: str
    path: str
    display_name: str | None = None


class DiscoveryController(Controller):
    path = "/api/v1/discovery"
    tags = ["discovery"]

    @get("/")
    async def list_discovered(self, account_service: AccountService) -> _DiscoverResponse:
        items = await account_service.discover_existing()
        return _DiscoverResponse(
            items=[
                _DiscoveredItem(
                    kind=c.kind,
                    path=c.path,
                    suggested_name=c.suggested_name,
                    is_logged_in=c.is_logged_in,
                    error=c.error,
                    backend_id=c.backend_id,
                )
                for c in items
            ]
        )

    @post("/import", status_code=status_codes.HTTP_201_CREATED)
    async def import_one(self, data: _ImportRequest, account_service: AccountService) -> BackendDTO:
        backend = await account_service.import_discovered(
            data.kind,
            data.path,
            display_name=data.display_name,
        )
        return BackendDTO.from_domain(
            backend,
            config_dir=str(account_service.config_dir(backend.id)),
        )
