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

from ai_accounts_core.backends._base import CliBackendBase
from ai_accounts_core.backends._cliproxy_chat import _chat_via_cliproxy
from ai_accounts_core.backends._iso import resolved_iso
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

_OPENCODE_URL_RE = re.compile(r"https://opencode\.ai/\S+")
_OPENCODE_SUCCESS_MARKERS = ("Authentication successful", "Logged in")
_OPENCODE_FAILURE_MARKERS = ("error:", "failed")


class _OpenCodeCliBrowserSession(LoginSession):
    def __init__(self, isolation_dir: Path) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._isolation_dir = isolation_dir
        self._done = False
        self._orchestrator: CliOrchestrator | None = None
        self._cleanup_lock = asyncio.Lock()

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

    async def _cleanup(self) -> None:
        async with self._cleanup_lock:
            if self._orchestrator is not None:
                try:
                    await self._orchestrator.terminate()
                except Exception:  # pragma: no cover - best-effort
                    pass
                try:
                    exit_code = await asyncio.wait_for(
                        self._orchestrator.wait(), timeout=10
                    )
                except asyncio.TimeoutError:
                    await self._orchestrator.kill()
                    await self._orchestrator.wait()
                except Exception:  # pragma: no cover - best-effort
                    pass

    async def events(self) -> AsyncIterator[LoginEvent]:
        # OPENCODE_HOME MUST be absolute — see codex backend for rationale.
        iso = self._isolation_dir.resolve()
        iso.mkdir(parents=True, exist_ok=True)
        self._orchestrator = CliOrchestrator(
            argv=["opencode", "auth", "login"],
            env={"OPENCODE_HOME": str(iso)},
            cwd=iso,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="opencode CLI not installed")
            return

        url_seen = False
        success = False
        try:
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
        finally:
            await self._cleanup()
            self._done = True

        if success:
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            yield LoginFailed(
                code="auth_failed",
                message="opencode auth login failed",
            )

    async def respond(self, answer: PromptAnswer) -> None:
        pass

    async def cancel(self) -> None:
        await self._cleanup()
        self._done = True


class _OpenCodeApiKeySession(LoginSession):
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
        return "opencode"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="api_key", prompt="OpenCode API key", hidden=True)
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


class OpenCodeBackend(CliBackendBase):
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

    # detect() inherited from CliBackendBase.

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        # opencode 0.x has no `auth check` subcommand. The real surface is
        # `opencode providers list` (alias `auth list`) which exits 0 even
        # when no providers are configured — must inspect stdout. Output
        # ends with either "N credentials" (where N>0 → ok) or "0
        # credentials" / "No providers" → not authenticated.
        # NOTE: opencode reads its auth.json from ~/.local/share/opencode
        # regardless of OPENCODE_HOME — true per-account isolation isn't
        # supported by the CLI yet (tracked separately).
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return False
        iso = resolved_iso(isolation_dir)
        env = self._env(credential, iso)
        rc, stdout, _stderr = await self._run(
            {"argv": [path, "providers", "list"], "env": env}
        )
        if rc != 0:
            return False
        # Strip ANSI escape sequences before matching.
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout.decode("utf-8", errors="replace"))
        text = text.strip().lower()
        if not text:
            return False
        if "0 credentials" in text or "no providers" in text or "no credentials" in text:
            return False
        # Match "N credentials" with N>=1.
        m = re.search(r"(\d+)\s+credentials?\b", text)
        if m:
            return int(m.group(1)) > 0
        # Fallback: assume non-empty meaningful output means authenticated.
        return True

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # Live discovery from OpenRouter — same pattern as gemini's Google AI
        # Studio probe. /v1/models is publicly readable; the api_key is sent
        # for parity with chat() and to satisfy any future auth requirement.
        # Returns OpenAI-style {data: [{id, name, context_length, ...}]}.
        api_key = credential.decode("utf-8", errors="replace").strip() if credential else ""
        if api_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as http:
                    resp = await http.get(
                        "https://openrouter.ai/api/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                if resp.status_code == 200:
                    raw = resp.json()
                    items = raw.get("data") if isinstance(raw, dict) else None
                    if isinstance(items, list) and items:
                        return [
                            Model(
                                id=str(m["id"]),
                                display_name=str(m.get("name") or m["id"]),
                                context_window=m.get("context_length"),
                            )
                            for m in items
                            if isinstance(m, dict) and m.get("id")
                        ]
            except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError):
                pass  # fall through to CLI shellout
        # CLI fallback for offline / API-down cases. opencode CLI's exact
        # `models --json` shape varies by version; tolerated empty result.
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return []
        env = self._env(credential, isolation_dir)
        rc, stdout, _stderr = await self._run(
            {"argv": [path, "models", "--json"], "env": env}
        )
        if rc != 0:
            from ai_accounts_core.backends._models_fallback import fallback

            return fallback("opencode")
        try:
            raw_cli: list[dict[str, Any]] = json.loads(stdout)
        except json.JSONDecodeError:
            from ai_accounts_core.backends._models_fallback import fallback

            return fallback("opencode")
        return [
            Model(
                id=item["id"],
                display_name=item.get("display_name", item["id"]),
                context_window=item.get("context_window"),
            )
            for item in raw_cli
            if item.get("id")
        ]

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        return []  # OpenRouter has no usage API

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
        messages_payload = [
            {"role": m.role.value, "content": m.content}
            for m in request.messages
        ]
        body: dict[str, object] = {
            "model": request.model,
            "messages": messages_payload,
            "stream": True,
        }
        if "max_tokens" in request.params:
            body["max_tokens"] = request.params["max_tokens"]
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
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
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    data = json.loads(payload)
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    text = delta.get("content")
                    if text:
                        yield ChatStreamEvent(kind="token", payload=text)
                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        yield ChatStreamEvent(
                            kind="done",
                            payload={
                                "finish_reason": finish_reason,
                                "model": data.get("model", request.model),
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
        return {
            **os.environ,
            "OPENCODE_API_KEY": credential.decode(),
            self._ISOLATION_ENV_VAR: str(isolation_dir),
        }

    # _run() inherited from CliBackendBase.
