from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.domain.chat import ChatRole
from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    LoginSession,
    PromptAnswer,
    TextPrompt,
)
from ai_accounts_core.login.cli_orchestrator import CliOrchestrator
from ai_accounts_core.login.interactive import run_interactive_cli_login
from ai_accounts_core.metadata import (
    BackendMetadata,
    InputSpec,
    InstallCheck,
    LoginFlowSpec,
    PlanOption,
)
from ai_accounts_core.protocols.backend import (
    ChatRequest,
    ChatStreamEvent,
    Model,
    PtyHandle,
    PtyRequest,
)

_CLAUDE_CONSOLE_URL_RE = re.compile(
    r"https://(?:claude\.ai|console\.anthropic\.com)/\S+"
)




class _ClaudeCliBrowserSession(LoginSession):
    """Interactive ``claude`` login session.

    Handles Claude Code's first-run TUI (theme picker, menus) before the
    OAuth URL appears. The interactive loop in
    :func:`run_interactive_cli_login` waits for REPL idle, then sends
    ``/login`` to trigger the browser-based auth.
    """

    ACTION_COMMAND = "/login"

    def __init__(self, isolation_dir: Path, config: dict | None = None) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._isolation_dir = isolation_dir
        self._config = config or {}
        self._done = False
        self._orchestrator: CliOrchestrator | None = None
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
        self._cleanup_lock = asyncio.Lock()
        self._credential: bytes | None = None

    @property
    def credential(self) -> bytes | None:
        return self._credential

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "claude"

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
                    await self._orchestrator.wait()
                except Exception:  # pragma: no cover - best-effort
                    pass

    async def events(self) -> AsyncIterator[LoginEvent]:
        # claude is launched bare (no /login arg): the first-run TUI runs
        # through its theme picker, then we send /login into the REPL.
        # Use user-supplied config_path if provided, falling back to isolation_dir.
        config_path = self._config.get("config_path")
        if config_path:
            expanded = Path(os.path.expanduser(str(config_path)))
            resolved = expanded.resolve()
            allowed_roots = (Path.home().resolve(), self._isolation_dir.resolve())
            if not any(resolved.is_relative_to(root) for root in allowed_roots):
                raise ValueError(
                    f"config_path '{config_path}' resolves outside allowed directories"
                )
            config_dir = resolved
            config_dir.mkdir(parents=True, exist_ok=True)
        else:
            config_dir = self._isolation_dir
        self._orchestrator = CliOrchestrator(
            argv=["claude"],
            env={"CLAUDE_CONFIG_DIR": str(config_dir)},
            cwd=self._isolation_dir,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="claude CLI not installed")
            return

        try:
            async for event in run_interactive_cli_login(
                orchestrator=self._orchestrator,
                answers=self._answers,
                progress_label="Starting claude /login",
                action_command=self.ACTION_COMMAND,
                url_regex=_CLAUDE_CONSOLE_URL_RE,
            ):
                # Send Enter to dismiss "Press Enter to continue"
                if isinstance(event, LoginComplete) and self._orchestrator:
                    try:
                        await self._orchestrator.write(b"\r")
                    except Exception:
                        pass
                yield event
        finally:
            await self._cleanup()
            self._done = True

    async def respond(self, answer: PromptAnswer) -> None:
        if self._done:
            return
        await self._answers.put(answer)

    async def cancel(self) -> None:
        await self._cleanup()
        self._done = True


class _ClaudeApiKeySession(LoginSession):
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
        return "claude"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="api_key", prompt="Anthropic API key", hidden=True)
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
        if not ans.answer.startswith("sk-ant-"):
            self._done = True
            yield LoginFailed(code="invalid_key", message="Invalid API key format")
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


class ClaudeBackend:
    kind: ClassVar[str] = "claude"
    _CLI_NAME: ClassVar[str] = "claude"
    _ISOLATION_ENV_VAR: ClassVar[str] = "CLAUDE_CONFIG_DIR"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key", "cli_browser"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="claude",
        display_name="Claude Code",
        icon_url=None,
        install_check=InstallCheck(
            command=["claude", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="cli_browser",
                display_name="Sign in with browser",
                description="Run `claude /login` and authenticate in your browser",
                requires_inputs=[],
            ),
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste an Anthropic API key (sk-ant-...)",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=[
            PlanOption(id="pro", label="Claude Pro", description="$20/mo"),
            PlanOption(id="max", label="Claude Max", description="$100+/mo"),
            PlanOption(id="api", label="API", description="Pay-as-you-go"),
        ],
        config_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "config_path": {"type": "string"},
                "plan": {"type": "string"},
            },
        },
        supports_multi_account=True,
        isolation_env_var="CLAUDE_CONFIG_DIR",
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "cli_browser":
            return _ClaudeCliBrowserSession(isolation_dir, config=config)
        if flow_kind == "api_key":
            return _ClaudeApiKeySession()
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
            {"argv": [path, "auth", "status"], "env": env}
        )
        return rc == 0

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return []
        env = self._env(credential, isolation_dir)
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

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        from ai_accounts_core.domain.usage import UsageWindow

        api_key = credential.decode("utf-8").strip()
        if api_key.startswith("sk-ant-"):
            return []  # API keys can't access usage endpoint
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.anthropic.com/api/oauth/usage",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "anthropic-beta": "oauth-2025-04-20",
                    },
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                windows = []
                for w in data.get("windows", []):
                    resets_at = None
                    if w.get("resets_at"):
                        from datetime import datetime

                        resets_at = datetime.fromisoformat(w["resets_at"])
                    windows.append(
                        UsageWindow(
                            window_type=w.get("window_type", "unknown"),
                            usage_percent=w.get("utilization", 0.0),
                            resets_at=resets_at,
                        )
                    )
                return windows
        except Exception:
            return []

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        api_key = credential.decode("utf-8").strip()

        # CLI-browser login: credential is empty, route through CLIProxyAPI
        if not api_key:
            from ai_accounts_core.backends._cliproxy_chat import _chat_via_cliproxy
            async for event in _chat_via_cliproxy(request):
                yield event
            return

        # API key login: call Anthropic API directly
        messages_payload = [
            {"role": m.role.value, "content": m.content}
            for m in request.messages
            if m.role != ChatRole.SYSTEM
        ]
        system_msgs = [
            m.content for m in request.messages if m.role == ChatRole.SYSTEM
        ]
        body: dict[str, object] = {
            "model": request.model,
            "messages": messages_payload,
            "max_tokens": request.params.get("max_tokens", 4096),
            "stream": True,
        }
        if system_msgs:
            body["system"] = system_msgs[0]
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                json=body,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
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
                    data = json.loads(line[6:])
                    if data.get("type") == "content_block_delta":
                        text = data.get("delta", {}).get("text", "")
                        if text:
                            yield ChatStreamEvent(
                                kind="token", payload=text
                            )
                    elif data.get("type") == "message_delta":
                        usage = data.get("usage", {})
                        yield ChatStreamEvent(
                            kind="done",
                            payload={
                                "finish_reason": data.get("delta", {}).get(
                                    "stop_reason", "stop"
                                ),
                                "tokens_out": usage.get("output_tokens"),
                                "model": request.model,
                            },
                        )

    async def _chat_via_proxy(
        self, request: ChatRequest
    ) -> AsyncIterator[ChatStreamEvent]:
        """Route chat through CLIProxyAPI's OpenAI-compatible endpoint."""
        from ai_accounts_core.cliproxy import detect_cliproxy

        proxy = detect_cliproxy()
        if proxy is None:
            yield ChatStreamEvent(
                kind="error",
                payload="CLIProxyAPI not running — install and start cliproxyapi, or use an API key",
            )
            return
        base_url, api_key = proxy
        messages = [
            {"role": m.role.value, "content": m.content}
            for m in request.messages
        ]
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json={"model": request.model, "messages": messages, "stream": True},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    yield ChatStreamEvent(kind="error", payload=f"Proxy error {resp.status_code}")
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
                    if text := delta.get("content"):
                        yield ChatStreamEvent(kind="token", payload=text)
                    if choice.get("finish_reason"):
                        usage = data.get("usage", {})
                        yield ChatStreamEvent(kind="done", payload={
                            "finish_reason": choice["finish_reason"],
                            "tokens_in": usage.get("prompt_tokens"),
                            "tokens_out": usage.get("completion_tokens"),
                            "model": request.model,
                        })

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
            "ANTHROPIC_API_KEY": credential.decode(),
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
