from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    LoginSession,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)
from ai_accounts_core.login.cli_orchestrator import CliOrchestrator
from ai_accounts_core.metadata import (
    BackendMetadata,
    InputSpec,
    InstallCheck,
    LoginFlowSpec,
)
from ai_accounts_core.protocols.backend import (
    ChatRequest,
    ChatStreamEvent,
    Model,
    PtyHandle,
    PtyRequest,
)

_OPENCODE_URL_RE = re.compile(r"https://opencode\.ai/\S+")
_OPENCODE_SUCCESS_MARKERS = ("Authentication successful", "Logged in")
_OPENCODE_FAILURE_MARKERS = ("error:", "failed")


class _OpenCodeCliBrowserSession(LoginSession):
    def __init__(self, isolation_dir: Path) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._isolation_dir = isolation_dir
        self._done = False
        self._orchestrator: CliOrchestrator | None = None

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "opencode"

    @property
    def flow_kind(self) -> str:
        return "cli_browser"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        self._orchestrator = CliOrchestrator(
            argv=["opencode", "auth", "login"],
            env={"OPENCODE_HOME": str(self._isolation_dir)},
            cwd=self._isolation_dir,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="opencode CLI not installed")
            return

        url_seen = False
        success = False
        async for chunk in self._orchestrator.read_output():
            if chunk.strip():
                yield StdoutChunk(text=chunk)
            if not url_seen:
                m = _OPENCODE_URL_RE.search(chunk)
                if m:
                    url_seen = True
                    yield UrlPrompt(prompt_id="auth", url=m.group(0))
            if any(mk in chunk for mk in _OPENCODE_SUCCESS_MARKERS):
                success = True
                break
            lower = chunk.lower()
            if "error" in lower or "failed" in lower or any(
                mk in chunk for mk in _OPENCODE_FAILURE_MARKERS
            ):
                break

        exit_code = await self._orchestrator.wait()
        self._done = True
        if success and exit_code == 0:
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            yield LoginFailed(
                code="cli_exit_nonzero" if exit_code != 0 else "auth_failed",
                message=f"opencode auth login exited with {exit_code}",
            )

    async def respond(self, answer: PromptAnswer) -> None:
        pass

    async def cancel(self) -> None:
        if self._orchestrator is not None and not self._done:
            await self._orchestrator.terminate()
            await self._orchestrator.wait()
        self._done = True


class _OpenCodeApiKeySession(LoginSession):
    def __init__(self) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
        self._done = False

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "opencode"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="api_key", prompt="OpenCode API key", hidden=True)
        ans = await self._answers.get()
        if not ans.answer:
            self._done = True
            yield LoginFailed(code="invalid_key", message="API key cannot be empty")
            return
        self._done = True
        yield LoginComplete(account_id="", backend_status="validating")

    async def respond(self, answer: PromptAnswer) -> None:
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True


class OpenCodeBackend:
    kind: ClassVar[str] = "opencode"
    _CLI_NAME: ClassVar[str] = "opencode"
    _ISOLATION_ENV_VAR: ClassVar[str] = "OPENCODE_HOME"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key", "cli_browser"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="opencode",
        display_name="OpenCode",
        icon_url=None,
        install_check=InstallCheck(
            command=["opencode", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="cli_browser",
                display_name="Sign in with browser",
                description="Opens a browser window to authenticate",
                requires_inputs=[],
            ),
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste an OpenCode API key",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {"email": {"type": "string"}},
        },
        supports_multi_account=True,
        isolation_env_var="OPENCODE_HOME",
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "cli_browser":
            return _OpenCodeCliBrowserSession(isolation_dir)
        if flow_kind == "api_key":
            return _OpenCodeApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

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
