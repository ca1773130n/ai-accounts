from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.ids import new_id
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
    r"https://[^\s]+/device/usercode|https://accounts\.google\.com/o/oauth2/device[^\s]*",
)
_CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")

_GEMINI_URL_RE = re.compile(r"https://accounts\.google\.com/o/oauth2/device/\S+")
_GEMINI_USER_CODE_RE = re.compile(r"([A-Z0-9]{4}-[A-Z0-9]{4})")
_GEMINI_SUCCESS_MARKERS = ("Login successful", "Authenticated")
_GEMINI_FAILURE_MARKERS = ("error:", "failed")


class _GeminiOAuthDeviceSession(LoginSession):
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
        return "gemini"

    @property
    def flow_kind(self) -> str:
        return "oauth_device"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        self._orchestrator = CliOrchestrator(
            argv=["gemini", "auth", "login", "--device"],
            env={"GEMINI_CLI_HOME": str(self._isolation_dir)},
            cwd=self._isolation_dir,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="gemini CLI not installed")
            return

        url: str | None = None
        user_code: str | None = None
        emitted_url_prompt = False
        success = False
        async for chunk in self._orchestrator.read_output():
            if chunk.strip():
                yield StdoutChunk(text=chunk)
            if url is None:
                m = _GEMINI_URL_RE.search(chunk)
                if m:
                    url = m.group(0)
            if user_code is None:
                m = _GEMINI_USER_CODE_RE.search(chunk)
                if m:
                    user_code = m.group(1)
            if not emitted_url_prompt and url and user_code:
                emitted_url_prompt = True
                yield UrlPrompt(prompt_id="device", url=url, user_code=user_code)
            if any(mk in chunk for mk in _GEMINI_SUCCESS_MARKERS):
                success = True
                break
            lower = chunk.lower()
            if "error" in lower or "failed" in lower or any(
                mk in chunk for mk in _GEMINI_FAILURE_MARKERS
            ):
                break

        exit_code = await self._orchestrator.wait()
        self._done = True
        if success and exit_code == 0:
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            yield LoginFailed(
                code="oauth_device_failed",
                message=f"gemini auth login exited with {exit_code}",
            )

    async def respond(self, answer: PromptAnswer) -> None:
        pass

    async def cancel(self) -> None:
        if self._orchestrator is not None and not self._done:
            await self._orchestrator.terminate()
            await self._orchestrator.wait()
        self._done = True


class _GeminiApiKeySession(LoginSession):
    def __init__(self) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
        self._done = False

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "gemini"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="api_key", prompt="Google AI Studio API key", hidden=True)
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


class GeminiBackend:
    kind: ClassVar[str] = "gemini"
    _CLI_NAME: ClassVar[str] = "gemini"
    _ISOLATION_ENV_VAR: ClassVar[str] = "GEMINI_CLI_HOME"
    _API_KEY_ENV_VAR: ClassVar[str] = "GEMINI_API_KEY"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key", "oauth_device"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="gemini",
        display_name="Gemini",
        icon_url=None,
        install_check=InstallCheck(
            command=["gemini", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="oauth_device",
                display_name="Sign in with Google",
                description="Sign in via Google device flow",
                requires_inputs=[],
            ),
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste a Google AI Studio API key",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
            },
        },
        supports_multi_account=True,
        isolation_env_var="GEMINI_CLI_HOME",
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "oauth_device":
            return _GeminiOAuthDeviceSession(isolation_dir)
        if flow_kind == "api_key":
            return _GeminiApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

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
            message=f"GeminiBackend does not support {flow.kind!r}",
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
            message=stderr_bytes.decode(errors="replace").strip() or "gemini auth exited non-zero",
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
            return LoginError(code="cli_missing", message="gemini CLI not found on PATH")

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
                message="gemini auth did not emit a challenge within 10s",
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
                message=f"could not parse verification challenge from gemini stdout: {text[:200]!r}",
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
