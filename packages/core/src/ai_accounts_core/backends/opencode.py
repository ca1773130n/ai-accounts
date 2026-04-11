from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.protocols.backend import (
    ChatRequest,
    ChatStreamEvent,
    CredentialLogin,
    LoginError,
    LoginFlow,
    LoginResult,
    Model,
    PtyHandle,
    PtyRequest,
)


class OpenCodeBackend:
    kind: ClassVar[str] = "opencode"
    _CLI_NAME: ClassVar[str] = "opencode"
    _ISOLATION_ENV_VAR: ClassVar[str] = "OPENCODE_HOME"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})

    async def detect(self) -> DetectResult:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return DetectResult(installed=False)
        rc, stdout, _stderr = await self._run({"argv": [path, "--version"]})
        if rc != 0:
            return DetectResult(installed=True, path=path, notes="version check failed")
        version: str | None = None
        if stdout:
            first_line = stdout.decode(errors="replace").strip().splitlines()[0]
            version = first_line or None
        return DetectResult(installed=True, version=version, path=path)

    async def login(self, flow: LoginFlow, *, isolation_dir: Path) -> LoginResult:
        if flow.kind != "api_key":
            return LoginError(
                code="unsupported_flow",
                message=f"OpenCodeBackend does not support {flow.kind!r}",
            )
        key = flow.inputs.get("api_key", "").strip()
        if not key:
            return LoginError(code="missing_input", message="api_key is required")
        return CredentialLogin(credential=key.encode())

    async def poll_login(self, handle: str, *, isolation_dir: Path) -> LoginResult:
        return LoginError(
            code="not_pollable",
            message="OpenCodeBackend only supports the synchronous api_key flow",
        )

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return False
        env = self._env(credential, isolation_dir)
        rc, _stdout, _stderr = await self._run(
            {"argv": [path, "auth", "check"], "env": env}
        )
        return rc == 0

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return []
        env = self._env(credential, isolation_dir)
        rc, stdout, _stderr = await self._run(
            {"argv": [path, "models", "--json"], "env": env}
        )
        if rc != 0:
            return []
        raw: list[dict[str, Any]] = json.loads(stdout)
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

    def _env(self, credential: bytes, isolation_dir: Path) -> dict[str, str]:
        isolation_dir.mkdir(parents=True, exist_ok=True)
        return {
            **os.environ,
            "OPENCODE_API_KEY": credential.decode(),
            self._ISOLATION_ENV_VAR: str(isolation_dir),
        }

    async def _run(self, spec: dict[str, Any]) -> tuple[int, bytes, bytes]:
        argv: list[str] = spec["argv"]
        env: dict[str, str] | None = spec.get("env")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout, stderr
