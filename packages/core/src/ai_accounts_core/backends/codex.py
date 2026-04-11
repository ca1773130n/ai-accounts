from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.backend import (
    ChatRequest,
    ChatStreamEvent,
    CredentialLogin,
    LoginError,
    LoginFlow,
    LoginResult,
    Model,
    OAuthDeviceLogin,
    PtyHandle,
    PtyRequest,
)

_URI_RE = re.compile(
    r"https://platform\.openai\.com[^\s]*|https://chat\.openai\.com[^\s]*|https://[^\s]+",
)
_CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")


class CodexBackend:
    kind: ClassVar[str] = "codex"
    _CLI_NAME: ClassVar[str] = "codex"
    _ISOLATION_ENV_VAR: ClassVar[str] = "CODEX_HOME"
    _API_KEY_ENV_VAR: ClassVar[str] = "OPENAI_API_KEY"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key", "oauth_device"})

    def __init__(self) -> None:
        self._oauth_procs: dict[str, asyncio.subprocess.Process] = {}
        self._oauth_challenges: dict[str, dict[str, str]] = {}

    async def detect(self) -> DetectResult:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return DetectResult(installed=False)
        rc, stdout, _stderr = await self._run({"argv": [path, "--version"]})
        if rc != 0:
            return DetectResult(installed=True, path=path, notes="version check failed")
        version = None
        if stdout:
            first_line = stdout.decode(errors="replace").strip().splitlines()[0]
            version = first_line or None
        return DetectResult(installed=True, version=version, path=path)

    async def login(
        self, flow: LoginFlow, *, isolation_dir: Path
    ) -> LoginResult:
        if flow.kind == "api_key":
            key = flow.inputs.get("api_key", "").strip()
            if not key:
                return LoginError(code="missing_input", message="api_key is required")
            return CredentialLogin(credential=key.encode())
        if flow.kind == "oauth_device":
            return await self._start_oauth_device(isolation_dir)
        return LoginError(
            code="unsupported_flow",
            message=f"CodexBackend does not support {flow.kind!r}",
        )

    async def poll_login(
        self, handle: str, *, isolation_dir: Path
    ) -> LoginResult:
        proc = self._oauth_procs.get(handle)
        if proc is None:
            return LoginError(code="unknown_handle", message=handle)

        if proc.returncode is None:
            challenge = self._oauth_challenges.get(handle, {})
            expires_at = datetime.now(UTC) + timedelta(minutes=15)
            return OAuthDeviceLogin(
                verification_uri=challenge.get("verification_uri", ""),
                user_code=challenge.get("user_code", ""),
                expires_at=expires_at,
                handle=handle,
            )

        if proc.returncode == 0:
            self._cleanup_handle(handle)
            return CredentialLogin(credential=b"")

        stderr_bytes = b""
        try:
            assert proc.stderr is not None
            stderr_bytes = await asyncio.wait_for(proc.stderr.read(4096), timeout=0.5)
        except Exception:
            pass
        self._cleanup_handle(handle)
        return LoginError(
            code="auth_failed",
            message=stderr_bytes.decode(errors="replace").strip() or "codex auth exited non-zero",
        )

    async def validate(
        self, credential: bytes, *, isolation_dir: Path
    ) -> bool:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return False
        env = self._env(credential, isolation_dir)
        rc, _stdout, _stderr = await self._run(
            {"argv": [path, "auth", "status"], "env": env}
        )
        return rc == 0

    async def list_models(
        self, credential: bytes, *, isolation_dir: Path
    ) -> list[Model]:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return []
        env = self._env(credential, isolation_dir)
        rc, stdout, _stderr = await self._run(
            {"argv": [path, "models", "list", "--json"], "env": env}
        )
        if rc != 0:
            return []
        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError:
            return []
        return [
            Model(
                id=item["id"],
                display_name=item.get("display_name", item["id"]),
                context_window=item.get("context_window"),
            )
            for item in raw
        ]

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        raise NotImplementedError("chat lands in Phase 3")

    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        raise NotImplementedError("pty lands in Phase 4")

    async def _start_oauth_device(self, isolation_dir: Path) -> LoginResult:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return LoginError(code="cli_missing", message="codex CLI not found on PATH")

        isolation_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, self._ISOLATION_ENV_VAR: str(isolation_dir)}

        proc = await asyncio.create_subprocess_exec(
            path, "auth", "login",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        assert proc.stdout is not None
        try:
            buf = await asyncio.wait_for(proc.stdout.read(2048), timeout=10.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except Exception:
                pass
            return LoginError(
                code="timeout",
                message="codex auth did not emit a challenge within 10s",
            )

        text = buf.decode(errors="replace")
        uri_match = _URI_RE.search(text)
        code_match = _CODE_RE.search(text)
        if not uri_match or not code_match:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except Exception:
                pass
            return LoginError(
                code="parse_failed",
                message=f"could not parse verification challenge from codex stdout: {text[:200]!r}",
            )

        handle = new_id("oauth")
        self._oauth_procs[handle] = proc
        challenge = {
            "verification_uri": uri_match.group(0),
            "user_code": code_match.group(1),
        }
        self._oauth_challenges[handle] = challenge

        return OAuthDeviceLogin(
            verification_uri=challenge["verification_uri"],
            user_code=challenge["user_code"],
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            handle=handle,
        )

    def _cleanup_handle(self, handle: str) -> None:
        self._oauth_procs.pop(handle, None)
        self._oauth_challenges.pop(handle, None)

    def _env(self, credential: bytes, isolation_dir: Path) -> dict[str, str]:
        isolation_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, self._ISOLATION_ENV_VAR: str(isolation_dir)}
        if credential:
            env[self._API_KEY_ENV_VAR] = credential.decode()
        return env

    async def _run(self, spec: dict[str, Any]) -> tuple[int, bytes, bytes]:
        argv = spec["argv"]
        env = spec.get("env")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout, stderr
