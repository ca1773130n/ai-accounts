"""Backend CLI install route."""

from __future__ import annotations

from litestar import Controller, post
from litestar.exceptions import HTTPException

from ai_accounts_core.install import InstallResult, install_backend_cli


class InstallController(Controller):
    path = "/api/v1/backends"
    tags = ["install"]

    @post("/{kind:str}/install", status_code=201)
    async def install(self, kind: str) -> InstallResult:
        try:
            result = await install_backend_cli(kind)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result
