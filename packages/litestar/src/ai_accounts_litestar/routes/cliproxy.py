"""CLIProxyAPI install + account registration routes."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import msgspec
from litestar import Controller, get, post

from ai_accounts_core.cliproxy import (
    CliproxyInstallResult,
    CliproxyLoginInfo,
    cliproxy_server_status,
    forward_cliproxy_callback,
    get_cliproxy_version,
    install_cliproxy,
    is_cliproxy_installed,
    start_cliproxy_login,
    start_cliproxy_server,
    stop_cliproxy_server,
)


class _StatusResponse(msgspec.Struct):
    installed: bool
    version: str | None
    binary_path: str | None


class _LoginBeginRequest(msgspec.Struct):
    backend_kind: str
    config_dir: str | None = None


class _LoginBeginResponse(msgspec.Struct):
    status: str  # "started" | "imported" | "skipped" | "error"
    message: str
    oauth_url: str | None = None
    device_code: str | None = None


class _ServerStartRequest(msgspec.Struct, kw_only=True):
    port: int = 8317
    api_key: str = "not-needed"


class _CallbackForwardRequest(msgspec.Struct):
    callback_url: str


class _CallbackForwardResponse(msgspec.Struct):
    status: str
    message: str


# Keep a lightweight registry of running proxy-login subprocesses so callers
# can extend their lifetime via the callback forward path.
_ACTIVE_PROCS: dict[str, object] = {}


class CliproxyController(Controller):
    path = "/api/v1/cliproxy"
    tags = ["cliproxy"]

    @get("/status")
    async def status(self) -> _StatusResponse:
        return _StatusResponse(
            installed=is_cliproxy_installed(),
            version=get_cliproxy_version(),
            binary_path=shutil.which("cliproxyapi"),
        )

    @post("/install", status_code=201)
    async def install(self) -> CliproxyInstallResult:
        return await install_cliproxy()

    @post("/login/begin", status_code=201)
    async def login_begin(self, data: _LoginBeginRequest) -> _LoginBeginResponse:
        config_dir = Path(data.config_dir) if data.config_dir else None
        proc, info = await start_cliproxy_login(
            backend_kind=data.backend_kind,
            config_dir=config_dir,
        )

        if info.error:
            return _LoginBeginResponse(
                status="error" if "not found" not in info.error else "skipped",
                message=info.error,
            )

        if info.imported:
            return _LoginBeginResponse(
                status="imported",
                message="Credentials imported (no browser required)",
            )

        if info.oauth_url is None:
            return _LoginBeginResponse(
                status="skipped",
                message="Proxy login did not produce an OAuth URL",
            )

        if proc is not None:
            proc_id = str(id(proc))
            _ACTIVE_PROCS[proc_id] = proc

            async def _reap() -> None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=300)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                finally:
                    _ACTIVE_PROCS.pop(proc_id, None)

            asyncio.create_task(_reap())

        return _LoginBeginResponse(
            status="started",
            message="Open the URL to complete authentication",
            oauth_url=info.oauth_url,
            device_code=info.device_code,
        )

    @post("/login/callback-forward")
    async def login_callback_forward(
        self, data: _CallbackForwardRequest
    ) -> _CallbackForwardResponse:
        result = await forward_cliproxy_callback(data.callback_url)
        return _CallbackForwardResponse(
            status=result["status"],
            message=result["message"],
        )

    @post("/server/start", status_code=200)
    async def server_start(self, data: _ServerStartRequest) -> dict:
        """Start CLIProxyAPI server with given port and api-key."""
        import asyncio
        import re

        if not (1024 <= data.port <= 65535):
            return {"status": "error", "port": data.port, "pid": None, "message": "port must be 1024-65535"}
        if not re.match(r"^[a-zA-Z0-9_-]+$", data.api_key):
            return {"status": "error", "port": data.port, "pid": None, "message": "api_key contains invalid characters"}
        # Run in thread to avoid blocking the event loop (sync polling loop inside)
        result = await asyncio.to_thread(
            start_cliproxy_server, port=data.port, api_key=data.api_key,
        )
        return result

    @post("/server/stop", status_code=200)
    async def server_stop(self) -> dict:
        """Stop running CLIProxyAPI server."""
        return stop_cliproxy_server()

    @get("/server/status")
    async def server_status(self) -> dict:
        """Get CLIProxyAPI server status (installed, running, port)."""
        return cliproxy_server_status()
