from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)

from ai_accounts_core.backends._iso import resolved_iso
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
from ai_accounts_core.login.interactive import (
    EAGER_FOLLOWUP_ENTER_SECONDS,
    EagerCodeState as _EagerCodeState,
    run_interactive_cli_login,
)
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
    r"https://(?:claude\.ai|claude\.com|console\.anthropic\.com|platform\.claude\.com)/\S+"
)




class _ClaudeCliBrowserSession(LoginSession):
    """Interactive ``claude`` login session.

    Runs the REPL-based v1 flow (``claude`` + ``/login``) because it is the
    only flow that accepts the OAuth code on stdin: after the TUI settles we
    send ``/login``, the CLI prints ``Paste code here if prompted > ``, and
    we forward the user-supplied code through the PTY.

    The v2 ``claude auth login --claudeai --email <email>`` command exists
    but **does not read stdin** — it expects an HTTP callback on a random
    local port, and ``platform.claude.com`` can't reach that port from the
    user's browser without coordinating the random port via JS.  We keep v1
    as the primary flow; if/when Anthropic drops v1, we'll need to extract
    the LISTEN port (``lsof -p PID -iTCP -sTCP:LISTEN``) and deliver the
    code+state as ``GET http://localhost:PORT/?code=X&state=Y``.
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
        # Shared flag between ``write_eager`` and the interactive login
        # loop's text-prompt handler — if the eager-paste form already
        # wrote the OAuth code, the loop must not block on ``answers.get()``
        # for the CLI's prompt the code already satisfied.
        self._eager_state = _EagerCodeState()

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
        # Use user-supplied config_path if provided, falling back to
        # isolation_dir. AccountService already validates ``config_path``
        # at create/update boundaries; we re-validate here as defence in
        # depth in case the domain object was constructed by another
        # path.
        from ai_accounts_core.services.accounts import _resolve_config_path_strict
        config_path = self._config.get("config_path")
        allowed_roots = (
            Path.home().resolve(),
            self._isolation_dir.resolve(),
            self._isolation_dir.parent.resolve(),
        )
        config_dir_from_cfg = _resolve_config_path_strict(
            config_path, allowed_roots=allowed_roots
        )
        if config_dir_from_cfg is not None:
            config_dir = resolved_iso(config_dir_from_cfg)
        else:
            config_dir = resolved_iso(self._isolation_dir)

        # Always use the v1 REPL + /login flow — it emits the
        # "Paste code here if prompted > " prompt and accepts the code on
        # stdin.  v2 (`claude auth login --claudeai`) does NOT read stdin
        # and would leave the wizard stuck waiting for an HTTP callback we
        # can't deliver.  The `email` config stays for forward-compat and
        # is currently only surfaced in the wizard's UI copy.
        argv = ["claude"]
        action_command: str | None = self.ACTION_COMMAND
        progress_label = "Starting claude /login"

        self._orchestrator = CliOrchestrator(
            argv=argv,
            env={"CLAUDE_CONFIG_DIR": str(config_dir)},
            cwd=resolved_iso(self._isolation_dir),
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
                progress_label=progress_label,
                action_command=action_command,
                url_regex=_CLAUDE_CONSOLE_URL_RE,
                eager_state=self._eager_state,
            ):
                # Send Enter to dismiss "Press Enter to continue"
                if isinstance(event, LoginComplete) and self._orchestrator:
                    try:
                        await self._orchestrator.write(b"\r")
                    except (OSError, asyncio.CancelledError) as exc:
                        logger.debug(
                            "post-login Enter write ignored: %r", exc
                        )
                yield event
        finally:
            await self._cleanup()
            self._done = True

    async def respond(self, answer: PromptAnswer) -> None:
        if self._done:
            return
        await self._answers.put(answer)

    async def write_eager(self, text: str) -> None:
        """Write directly to the CLI's stdin.

        Writes the pasted OAuth code plus a submit ``\\r``. Claude v2.1's
        TUI holds the "Login successful. Press Enter to continue…" message
        behind an internal redraw gate — until another Enter is received
        the success line is never flushed to stdout and our login loop
        sits waiting on the regex.  We schedule a best-effort follow-up
        ``\\r`` a few seconds later to unblock that redraw.  On the error
        path the follow-up simply dismisses "Press Enter to retry".

        The code is short-lived OAuth credential material; only its length
        is logged, never its contents or a preview.
        """
        if self._done or self._orchestrator is None:
            logger.warning(
                "write_eager skipped: done=%s orchestrator_ready=%s",
                self._done, self._orchestrator is not None,
            )
            return
        cleaned = text.strip()
        payload = (cleaned + "\r").encode()
        # Mark the eager state BEFORE the write so a racing text-prompt
        # handler sees it immediately. Log only the length — never a
        # preview — so OAuth codes don't leak into logs/CI/support bundles.
        self._eager_state.sent = True
        self._eager_state.length = len(cleaned)
        self._eager_state.at_monotonic = time.monotonic()
        logger.info("write_eager: writing %d bytes to PTY", len(payload))
        try:
            await self._orchestrator.write(payload)
        except (OSError, asyncio.CancelledError):
            logger.exception("write_eager: write failed")
            return

        async def _followup_enter() -> None:
            await asyncio.sleep(EAGER_FOLLOWUP_ENTER_SECONDS)
            if self._done or self._orchestrator is None:
                return
            try:
                await self._orchestrator.write(b"\r")
                logger.info("write_eager: follow-up Enter sent to flush TUI")
            except Exception:  # pragma: no cover
                logger.warning("write_eager: follow-up Enter failed", exc_info=True)

        asyncio.create_task(_followup_enter())

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
                description=(
                    "Launch `claude` in a PTY, drive the first-run theme/"
                    "config menus, send `/login`, and consume the OAuth "
                    "paste-code from the wizard's eager form."
                ),
                requires_inputs=[
                    InputSpec(
                        name="email",
                        label="Email (optional — prefills Claude sign-in page)",
                        kind="email",
                    ),
                ],
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
        # Claude CLI v1/v2 has no `auth status` subcommand. We validate by:
        #   1. Confirming the binary is on PATH (sanity).
        #   2. Confirming `<isolation>/.credentials.json` exists, is non-empty,
        #      and parses as JSON. This is the file the CLI writes after a
        #      successful /login flow.
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return False
        iso = resolved_iso(isolation_dir)
        creds_file = iso / ".credentials.json"
        if not creds_file.is_file():
            return False
        try:
            data = json.loads(creds_file.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        return bool(data)

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # Claude CLI has no `models list` subcommand. Return a static set of
        # the public Anthropic models; live discovery happens upstream via
        # CLIProxyAPI's /v1/models when the proxy is registered.
        return [
            Model(
                id="claude-opus-4-7",
                display_name="Claude Opus 4.7",
                context_window=1_000_000,
            ),
            Model(
                id="claude-sonnet-4-6",
                display_name="Claude Sonnet 4.6",
                context_window=1_000_000,
            ),
            Model(
                id="claude-haiku-4-5-20251001",
                display_name="Claude Haiku 4.5",
                context_window=200_000,
            ),
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
        except (httpx.HTTPError, ValueError, KeyError, OSError) as exc:
            logger.debug("get_usage failed: %r", exc)
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
        env.update(self._env(credential, resolved_iso(isolation_dir)))
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
