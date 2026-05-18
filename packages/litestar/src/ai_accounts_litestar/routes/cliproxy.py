"""CLIProxyAPI install + account registration routes."""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

import msgspec
from ai_accounts_core.cliproxy import (
    CliproxyInstallResult,
    cliproxy_server_status,
    forward_cliproxy_callback,
    get_cliproxy_version,
    install_cliproxy,
    is_cliproxy_installed,
    start_cliproxy_login,
    start_cliproxy_server,
    stop_cliproxy_server,
)
from litestar import Controller, get, post


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
    session_id: str | None = None  # set when proc is running; key for /login/status


class _LoginStatusResponse(msgspec.Struct):
    state: str  # "running" | "completed" | "failed" | "timeout" | "unknown"
    message: str
    returncode: int | None = None


class _ServerStartRequest(msgspec.Struct, kw_only=True):
    port: int = 8317
    api_key: str = "not-needed"


class _CallbackForwardRequest(msgspec.Struct):
    callback_url: str


class _CallbackForwardResponse(msgspec.Struct):
    status: str
    message: str


logger = logging.getLogger(__name__)

# Keep a lightweight registry of running proxy-login subprocesses so callers
# can extend their lifetime via the callback forward path.
_ACTIVE_PROCS: dict[str, object] = {}
_ACTIVE_TASKS: dict[str, asyncio.Task[None]] = {}
# Final state of completed login sessions, keyed by the same session_id as
# _ACTIVE_PROCS. Lets the device-code flow poll for completion: cliproxyapi
# polls OpenAI server-side and exits 0 on success — no browser callback.
# Bounded LRU eviction keeps this from growing unbounded.
_LOGIN_STATE: dict[str, dict[str, object]] = {}
_LOGIN_STATE_MAX = 64


def _record_login_state(session_id: str, state: str, message: str, returncode: int | None) -> None:
    if len(_LOGIN_STATE) >= _LOGIN_STATE_MAX:
        # Drop oldest entry (insertion order in dicts ≥ 3.7)
        oldest = next(iter(_LOGIN_STATE), None)
        if oldest is not None:
            _LOGIN_STATE.pop(oldest, None)
    _LOGIN_STATE[session_id] = {"state": state, "message": message, "returncode": returncode}


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

        proc_id: str | None = None
        if proc is not None:
            # Closes RISKS-AND-BUGS L-2: don't key on id(proc). Python can
            # reuse an object's id after GC, so a long-running process
            # cycling subprocesses could in theory overwrite a live entry.
            # uuid4 gives us a per-process key that's stable for the entry's
            # lifetime.
            proc_id = uuid.uuid4().hex
            _ACTIVE_PROCS[proc_id] = proc
            _record_login_state(proc_id, "running", "Awaiting OAuth completion", None)
            reap_info = info  # capture for closure
            captured_proc_id = proc_id

            async def _reap() -> None:
                timed_out = False
                try:
                    await asyncio.wait_for(proc.wait(), timeout=300)
                except TimeoutError:
                    timed_out = True
                    proc.kill()
                    await proc.wait()
                # Drain any remaining stdout so cliproxyapi never blocks on
                # a full pipe buffer mid-flow. We also use the tail to
                # disambiguate success/failure when returncode alone isn't
                # decisive.
                tail = ""
                if proc.stdout is not None:
                    try:
                        remaining = await proc.stdout.read()
                        tail = remaining.decode(errors="replace")[-2048:]
                    except Exception:
                        pass
                rc = proc.returncode
                if timed_out:
                    state, msg = "timeout", "Login timed out after 5 minutes"
                elif rc == 0:
                    state, msg = "completed", "API proxy login completed"
                else:
                    state = "failed"
                    msg = (tail.strip().splitlines() or [f"cliproxyapi exited with code {rc}"])[-1]
                _record_login_state(captured_proc_id, state, msg, rc)
                _ACTIVE_PROCS.pop(captured_proc_id, None)
                if reap_info.fake_dir:
                    import shutil as _shutil

                    _shutil.rmtree(reap_info.fake_dir, ignore_errors=True)

            asyncio.create_task(_reap())

        return _LoginBeginResponse(
            status="started",
            message="Open the URL to complete authentication",
            oauth_url=info.oauth_url,
            device_code=info.device_code,
            session_id=proc_id,
        )

    @get("/login/status")
    async def login_status(self, session_id: str) -> _LoginStatusResponse:
        entry = _LOGIN_STATE.get(session_id)
        if entry is None:
            return _LoginStatusResponse(state="unknown", message="No such session")
        return _LoginStatusResponse(
            state=str(entry["state"]),
            message=str(entry["message"]),
            returncode=entry["returncode"],  # type: ignore[arg-type]
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
            return {
                "status": "error",
                "port": data.port,
                "pid": None,
                "message": "port must be 1024-65535",
            }
        if not re.match(r"^[a-zA-Z0-9_-]+$", data.api_key):
            return {
                "status": "error",
                "port": data.port,
                "pid": None,
                "message": "api_key contains invalid characters",
            }
        # Run in thread to avoid blocking the event loop (sync polling loop inside)
        result = await asyncio.to_thread(
            start_cliproxy_server,
            port=data.port,
            api_key=data.api_key,
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
