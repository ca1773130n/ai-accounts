from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import httpx

from ai_accounts_core.backends._cliproxy_chat import _chat_via_cliproxy
from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.domain.chat import ChatRole
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

def _validate_config_path(config_path: str | None, isolation_dir: Path) -> Path:
    """Validate config_path is safe. Returns the resolved gemini config dir."""
    if not config_path:
        return Path.home() / ".gemini"
    expanded = Path(os.path.expanduser(str(config_path)))
    resolved = expanded.resolve()
    # Must not escape outside home or isolation directory
    allowed_roots = (Path.home().resolve(), isolation_dir.resolve())
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise ValueError(f"config_path '{config_path}' resolves outside allowed directories")
    return resolved / ".gemini"


_GEMINI_URL_RE = re.compile(r"https://accounts\.google\.com/o/oauth2/device/\S+")
_GEMINI_USER_CODE_RE = re.compile(r"([A-Z0-9]{4}-[A-Z0-9]{4})")
_GEMINI_SUCCESS_MARKERS = ("Login successful", "Authenticated")
_GEMINI_FAILURE_MARKERS = ("error:", "failed")


class _GeminiApiKeySession(LoginSession):
    def __init__(self) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue(maxsize=1)
        self._done = False
        self._credential: bytes | None = None

    @property
    def credential(self) -> bytes | None:
        return self._credential

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
        try:
            ans = await asyncio.wait_for(self._answers.get(), timeout=300)
        except asyncio.TimeoutError:
            self._done = True
            yield LoginFailed(code="response_timeout", message="No response received within 5 minutes")
            return
        if ans.prompt_id == "__cancel__":
            self._done = True
            yield LoginFailed(code="cancelled", message="Login cancelled")
            return
        if not ans.answer:
            self._done = True
            yield LoginFailed(code="invalid_key", message="API key cannot be empty")
            return
        self._credential = ans.answer.encode("utf-8")
        self._done = True
        yield LoginComplete(account_id="", backend_status="validating")

    async def respond(self, answer: PromptAnswer) -> None:
        if self._done:
            return
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True
        with contextlib.suppress(asyncio.QueueFull):
            self._answers.put_nowait(PromptAnswer(prompt_id="__cancel__", answer=""))


class GeminiBackend:
    kind: ClassVar[str] = "gemini"
    _CLI_NAME: ClassVar[str] = "gemini"
    _ISOLATION_ENV_VAR: ClassVar[str] = "GEMINI_CLI_HOME"
    _API_KEY_ENV_VAR: ClassVar[str] = "GEMINI_API_KEY"
    # Gemini CLI 0.35.3 has NO `auth` subcommand — `gemini auth login --device`
    # does not exist. Authentication is set via env vars: GEMINI_API_KEY (API
    # key flow), GOOGLE_GENAI_USE_VERTEXAI (Vertex), or GOOGLE_GENAI_USE_GCA
    # (interactive Google Cloud OAuth, browser-only). The OAuth flows we used
    # to advertise (oauth_device / direct_oauth) cannot be reliably driven
    # from a wizard subprocess. Until that's reworked, only api_key is
    # advertised; users paste a Google AI Studio key.
    supported_login_flows: ClassVar[frozenset[str]] = frozenset(
        {"api_key"}
    )

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
                kind="api_key",
                display_name="API key",
                description=(
                    "Paste a Google AI Studio API key (the OAuth flows for "
                    "Gemini CLI 0.35+ are not yet supported here — get a key "
                    "from https://aistudio.google.com/apikey)"
                ),
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
        if flow_kind == "api_key":
            return _GeminiApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

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

    async def validate(
        self, credential: bytes, *, isolation_dir: Path
    ) -> bool:
        # Gemini CLI 0.35+ has no `auth status` subcommand. For the api_key
        # flow we validate the credential directly against Google AI Studio's
        # `models` endpoint — a 200 means the key is accepted, anything else
        # is a failure.
        if not credential:
            return False
        api_key = credential.decode("utf-8", errors="replace").strip()
        if not api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": api_key},
                )
        except (httpx.HTTPError, OSError):
            return False
        return resp.status_code == 200

    async def list_models(
        self, credential: bytes, *, isolation_dir: Path
    ) -> list[Model]:
        # Gemini CLI 0.35+ has no `models list` subcommand. Probe Google AI
        # Studio's models endpoint directly with the API key — no isolation_dir
        # needed for this path.
        if not credential:
            return []
        api_key = credential.decode("utf-8", errors="replace").strip()
        if not api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": api_key},
                )
        except (httpx.HTTPError, OSError):
            return []
        if resp.status_code != 200:
            return []
        try:
            raw_data = resp.json()
        except (ValueError, json.JSONDecodeError):
            return []
        items = raw_data.get("models", [])
        return [
            Model(
                id=m.get("name", "").rsplit("/", 1)[-1],
                display_name=m.get("displayName", m.get("name", "")),
                context_window=m.get("inputTokenLimit"),
            )
            for m in items
            if m.get("name")
        ]

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        from ai_accounts_core.domain.usage import UsageWindow

        api_key = credential.decode("utf-8").strip()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
                    json={"project": "cloud-code-assist"},
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                windows = []
                for bucket in data.get("buckets", []):
                    remaining = bucket.get("remainingFraction", 1.0)
                    resets_at = None
                    if bucket.get("resetTime"):
                        from datetime import datetime

                        resets_at = datetime.fromisoformat(bucket["resetTime"])
                    windows.append(
                        UsageWindow(
                            window_type=bucket.get("modelId", "unknown"),
                            usage_percent=(1.0 - remaining) * 100.0,
                            resets_at=resets_at,
                        )
                    )
                return windows
        except (httpx.HTTPError, ValueError, KeyError, OSError):
            return []

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        api_key = credential.decode("utf-8").strip()
        if not api_key:
            async for event in _chat_via_cliproxy(request):
                yield event
            return
        contents = []
        for m in request.messages:
            if m.role == ChatRole.SYSTEM:
                continue
            role = "model" if m.role == ChatRole.ASSISTANT else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        body: dict[str, object] = {"contents": contents}
        system_msgs = [
            m.content for m in request.messages if m.role == ChatRole.SYSTEM
        ]
        if system_msgs:
            body["system_instruction"] = {"parts": [{"text": system_msgs[0]}]}
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{request.model}:streamGenerateContent?alt=sse&key={api_key}"
        )
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                url,
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    yield ChatStreamEvent(
                        kind="error",
                        payload=f"API error {resp.status_code}",
                    )
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    candidate = candidates[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    if parts:
                        text = parts[0].get("text", "")
                        if text:
                            yield ChatStreamEvent(
                                kind="token", payload=text
                            )
                    finish_reason = candidate.get("finishReason")
                    if finish_reason:
                        yield ChatStreamEvent(
                            kind="done",
                            payload={
                                "finish_reason": finish_reason,
                                "model": request.model,
                            },
                        )

    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        from ai_accounts_core.pty.handle import AsyncPtyHandle

        env = dict(request.env)
        env.update(self._env(credential, isolation_dir))
        return await AsyncPtyHandle.spawn(
            command=request.command, cols=request.cols, rows=request.rows, env=env,
        )

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
