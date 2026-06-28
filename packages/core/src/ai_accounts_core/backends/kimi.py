from __future__ import annotations

import asyncio
import contextlib
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

from ai_accounts_core.backends._base import CliBackendBase
from ai_accounts_core.backends._cliproxy_chat import _chat_via_cliproxy
from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    LoginSession,
    PromptAnswer,
    TextPrompt,
    UrlPrompt,
)
from ai_accounts_core.metadata import (
    BackendMetadata,
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


class _KimiCliProxySession(LoginSession):
    """OAuth login that delegates to ``cliproxyapi -kimi-login``.

    Kimi (Moonshot) has no scriptable OAuth subcommand we can drive
    from a wizard subprocess. Sidesteps by spawning cliproxyapi which
    handles the Moonshot OAuth handshake and writes a credential to its
    auth directory. The user pastes the localhost callback URL the
    browser is redirected to — same UX as the antigravity cliproxy flow.

    Yields:
        UrlPrompt   — Moonshot OAuth URL (open in browser)
        TextPrompt  — "paste callback URL"
        LoginComplete on success / LoginFailed on error.

    The session's credential is empty bytes — cliproxyapi owns the
    auth file. ``KimiBackend.validate`` falls back to a cliproxy
    /v1/models probe to confirm.
    """

    def __init__(self) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue(maxsize=1)
        self._done = False
        self._proc: Any = None
        self._fake_dir: Path | None = None

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "kimi"

    @property
    def flow_kind(self) -> str:
        return "cli_browser"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        from ai_accounts_core.cliproxy import (
            forward_cliproxy_callback,
            start_cliproxy_login,
        )

        proc, info = await start_cliproxy_login("kimi")
        self._proc = proc
        if info.fake_dir:
            self._fake_dir = Path(info.fake_dir)
        if info.error:
            self._done = True
            yield LoginFailed(code="cliproxy_unavailable", message=info.error)
            return
        if info.imported:
            # cliproxyapi reused a cached credential — already logged in.
            self._done = True
            yield LoginComplete(account_id="", backend_status="validating")
            return
        if not info.oauth_url:
            self._done = True
            yield LoginFailed(
                code="no_oauth_url",
                message="cliproxyapi did not produce an OAuth URL",
            )
            return
        yield UrlPrompt(prompt_id="kimi_oauth", url=info.oauth_url)
        # Same paste-callback shape as the antigravity cliproxy flow. After
        # signing in, Moonshot redirects the browser to a localhost
        # callback; when the user is on a remote machine that localhost
        # is THEIR machine, not the playground host, so the redirect
        # appears to hang. The URL itself is still in the address bar and
        # contains the auth code — tell the user explicitly so they don't
        # think login is broken.
        yield TextPrompt(
            prompt_id="callback",
            prompt=(
                "After signing in, your browser will try to load a "
                "http://localhost callback and likely show 'this site "
                "can't be reached' or just keep loading. That's expected "
                "— the URL itself contains your auth code. Copy the FULL "
                "URL from the address bar and paste it here, then click "
                "Send."
            ),
            hidden=False,
        )
        try:
            ans = await asyncio.wait_for(self._answers.get(), timeout=300)
        except TimeoutError:
            self._done = True
            yield LoginFailed(code="response_timeout", message="No response within 5 minutes")
            return
        if ans.prompt_id == "__cancel__":
            self._done = True
            yield LoginFailed(code="cancelled", message="Login cancelled")
            return
        if not ans.answer:
            self._done = True
            yield LoginFailed(
                code="invalid_callback",
                message="Callback URL cannot be empty",
            )
            return
        result = await forward_cliproxy_callback(ans.answer)
        self._done = True
        if result.get("status") == "completed":
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            yield LoginFailed(
                code="callback_forward_failed",
                message=str(result.get("message") or "Callback forwarding failed"),
            )

    async def respond(self, answer: PromptAnswer) -> None:
        if self._done:
            return
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True
        with contextlib.suppress(asyncio.QueueFull):
            self._answers.put_nowait(PromptAnswer(prompt_id="__cancel__", answer=""))
        # Best-effort proc kill + fake_dir cleanup — start_cliproxy_login
        # spawns a subprocess and a temp PATH-shim dir; both must be
        # reaped if the user aborts mid-flow.
        proc = self._proc
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.kill()
                await proc.wait()
        if self._fake_dir is not None:
            shutil.rmtree(self._fake_dir, ignore_errors=True)


class KimiBackend(CliBackendBase):
    kind: ClassVar[str] = "kimi"
    # Keyless — no terminal CLI to install. OAuth is delegated to
    # cliproxyapi (-kimi-login), chat routes through cliproxyapi's
    # OpenAI-compatible endpoint.
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"cli_browser"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="kimi",
        display_name="Kimi (Moonshot)",
        icon_url=None,
        # No binary to probe — cliproxyapi owns the OAuth handshake. The
        # benign command keeps install_check non-blocking.
        install_check=InstallCheck(command=["true"], version_regex=r"(\d+)?"),
        login_flows=[
            LoginFlowSpec(
                kind="cli_browser",
                display_name="Sign in with Moonshot",
                description=(
                    "Sign in to your Kimi (Moonshot) account via "
                    "CLIProxyAPI. No CLI required — OAuth runs in your "
                    "browser."
                ),
                requires_inputs=[],
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
        isolation_env_var=None,
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "cli_browser":
            return _KimiCliProxySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    async def detect(self) -> DetectResult:
        # Keyless backend — nothing to install locally. cliproxyapi owns
        # the OAuth credential; report available so the wizard's CLI step
        # is a non-blocking "No CLI required" note.
        return DetectResult(installed=True, notes="No CLI required")

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        # Credential is empty after the cli_browser flow — cliproxyapi
        # owns the auth file. Validate by asking cliproxy if it lists any
        # kimi models; non-empty list = ready.
        from ai_accounts_core.cliproxy import cliproxy_list_models

        return bool(await cliproxy_list_models("kimi"))

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        from ai_accounts_core.cliproxy import cliproxy_list_models

        live = await cliproxy_list_models("kimi")
        if live:
            return [
                Model(
                    id=str(m["id"]),
                    display_name=str(m.get("display_name") or m["id"]),
                    context_window=m.get("context_window"),
                )
                for m in live
            ]
        from ai_accounts_core.backends._models_fallback import fallback

        return fallback("kimi")

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        # Moonshot exposes no quota endpoint we route through cliproxy.
        return []

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        async for event in _chat_via_cliproxy(request):
            yield event

    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        from ai_accounts_core.pty.handle import AsyncPtyHandle

        return await AsyncPtyHandle.spawn(
            command=request.command,
            cols=request.cols,
            rows=request.rows,
            env=dict(request.env),
        )
