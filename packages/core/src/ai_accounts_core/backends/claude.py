from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.protocols.backend import (
    ChatRequest,
    ChatStreamEvent,
    LoginFlow,
    Model,
    PtyHandle,
    PtyRequest,
)


class ClaudeBackend:
    kind: ClassVar[str] = "claude"
    _CLI_NAME: ClassVar[str] = "claude"

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

    async def login(self, flow: LoginFlow) -> bytes:
        if flow.kind == "api_key":
            key = flow.inputs.get("api_key", "").strip()
            if not key:
                raise ValueError("api_key input is required for api_key flow")
            return key.encode()
        raise ValueError(f"unsupported login flow: {flow.kind}")

    async def validate(self, credential: bytes) -> bool:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return False
        env = {**os.environ, "ANTHROPIC_API_KEY": credential.decode()}
        rc, _stdout, _stderr = await self._run(
            {"argv": [path, "auth", "status"], "env": env}
        )
        return rc == 0

    async def list_models(self, credential: bytes) -> list[Model]:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return []
        env = {**os.environ, "ANTHROPIC_API_KEY": credential.decode()}
        rc, stdout, _stderr = await self._run(
            {"argv": [path, "models", "list", "--json"], "env": env}
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
        self, request: ChatRequest, credential: bytes
    ) -> AsyncIterator[ChatStreamEvent]:
        raise NotImplementedError("chat lands in Phase 3")

    async def pty(self, request: PtyRequest, credential: bytes) -> PtyHandle:
        raise NotImplementedError("pty lands in Phase 4")

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
