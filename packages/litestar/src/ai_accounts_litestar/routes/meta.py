"""Backend metadata aggregation route."""

from __future__ import annotations

import msgspec
from ai_accounts_core.metadata import BackendMetadata, BackendRegistry
from litestar import Controller, get


class _MetaResponse(msgspec.Struct, kw_only=True):
    items: list[BackendMetadata]


class MetaController(Controller):
    path = "/api/v1/backends"
    tags = ["metadata"]

    @get("/_meta")
    async def list_metadata(self, backend_registry: BackendRegistry) -> _MetaResponse:
        return _MetaResponse(items=backend_registry.list())
