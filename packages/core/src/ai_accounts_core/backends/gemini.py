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
from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.domain.chat import ChatRole
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


class _GeminiCliProxySession(LoginSession):
    """OAuth login that delegates to ``cliproxyapi --login``.

    Gemini CLI 0.35+ has no scriptable OAuth subcommand we can drive
    from a wizard subprocess. Sidesteps by spawning cliproxyapi which
    handles the Google OAuth handshake (subscription / Google AI Pro)
    and writes a ``gemini-<email>.json`` to its auth directory. The
    user pastes the localhost callback URL the browser is redirected
    to — same UX as the existing optional cliproxy registration step.

    Yields:
        UrlPrompt   — Google OAuth URL (open in browser)
        TextPrompt  — "paste callback URL"
        LoginComplete on success / LoginFailed on error.

    The session's credential is empty bytes — cliproxyapi owns the
    auth file. ``GeminiBackend.validate`` falls back to a cliproxy
    /v1/models probe filtered by ``owned_by=google`` to confirm.
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
        return "gemini"

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

        proc, info = await start_cliproxy_login("gemini")
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
        yield UrlPrompt(prompt_id="gemini_oauth", url=info.oauth_url)
        # Same paste-callback shape as the cliproxy registration step in
        # the wizard (Step 3.5). After signing in, Google redirects the
        # browser to http://localhost:8085/oauth2callback?code=…&state=…;
        # when the user is on a remote machine that localhost is THEIR
        # machine, not the playground host, so the redirect appears to
        # hang ("this site can't be reached" / spinner). The URL itself
        # is still in the address bar and contains the auth code we need
        # — tell the user explicitly so they don't think login is broken.
        yield TextPrompt(
            prompt_id="callback",
            prompt=(
                "After signing in, your browser will try to load "
                "http://localhost:8085/oauth2callback?... and likely "
                "show 'this site can't be reached' or just keep loading. "
                "That's expected — the URL itself contains your auth "
                "code. Copy the FULL URL from the address bar and paste "
                "it here, then click Send."
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
        # The TextPrompt's `prompt` text is the input label rendered by
        # LoginStream. Mention the AI Studio URL there so the user knows
        # where to get a key — but DON'T auto-open the URL: the user
        # wanted control over when (and whether) a new tab pops up.
        yield TextPrompt(
            prompt_id="api_key",
            prompt=(
                "Paste a Google AI Studio API key (get one at https://aistudio.google.com/apikey)"
            ),
            hidden=True,
        )
        try:
            ans = await asyncio.wait_for(self._answers.get(), timeout=300)
        except TimeoutError:
            self._done = True
            yield LoginFailed(
                code="response_timeout", message="No response received within 5 minutes"
            )
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


class GeminiBackend(CliBackendBase):
    kind: ClassVar[str] = "gemini"
    _CLI_NAME: ClassVar[str] = "gemini"
    _ISOLATION_ENV_VAR: ClassVar[str] = "GEMINI_CLI_HOME"
    _API_KEY_ENV_VAR: ClassVar[str] = "GEMINI_API_KEY"
    # Gemini CLI 0.35.3 has NO `auth` subcommand — `gemini auth login --device`
    # does not exist. Two viable auth paths in this codebase:
    #
    #   * cli_browser: delegates to `cliproxyapi --login` for the Google
    #     OAuth handshake (subscription / Gemini Code Assist / Pro).
    #     cliproxyapi writes the credential to its auth dir; chat() then
    #     routes through cliproxyapi's OpenAI-compatible endpoint.
    #   * api_key: paste a Google AI Studio key — direct API access, no
    #     subscription needed. Stored in our vault.
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"cli_browser", "api_key"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="gemini",
        display_name="Antigravity",
        icon_url=None,
        install_check=InstallCheck(
            command=["gemini", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            # api_key is FIRST so the wizard's auto-pick lands on the path
            # that actually works for everyone. cli_browser delegates to
            # cliproxyapi --login which uses a hardcoded OAuth client that
            # frequently hangs on Google's consent screen (unverified app
            # gate, Workspace policy blocks, browser extension issues).
            # cli_browser stays available via the wizard's flow switcher
            # for users where it does work (Gemini Code Assist / Pro).
            LoginFlowSpec(
                kind="api_key",
                display_name="Gemini API key (Google AI Studio)",
                description=(
                    "Paste a Google AI Studio API key — direct, no OAuth. "
                    "Get one at https://aistudio.google.com/apikey "
                    "(opens automatically in the next step)."
                ),
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
            LoginFlowSpec(
                kind="cli_browser",
                display_name="Sign in with Antigravity (subscription)",
                description=(
                    "Sign in to your Google Antigravity subscription via "
                    "CLIProxyAPI. Works with Gemini Code Assist / Pro / Ultra "
                    "plans. NOTE: Google's OAuth consent gate can be "
                    "unreliable for this client; if it hangs, switch back "
                    "to the Gemini API key."
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
        if flow_kind == "cli_browser":
            return _GeminiCliProxySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    async def detect(self) -> DetectResult:
        # Antigravity needs no terminal CLI — OAuth runs through cliproxyapi's
        # `-antigravity-login`. The legacy `gemini` binary is no longer
        # installed, so report available to keep the wizard's CLI step a
        # non-blocking "No CLI required" note rather than probing for it.
        return DetectResult(installed=True, notes="No CLI required")

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        # Gemini CLI 0.35+ has no `auth status` subcommand. Two paths:
        #
        #   * api_key flow — credential bytes hold the key. Validate by
        #     hitting Google AI Studio's `models` endpoint; 200 = ready.
        #   * cli_browser flow — credential is empty (cliproxyapi owns
        #     the auth file at ~/.cli-proxy-api/gemini-<email>.json).
        #     Validate by asking cliproxy if it lists any google-owned
        #     models; non-empty list = ready.
        api_key = credential.decode("utf-8", errors="replace").strip() if credential else ""
        if api_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as http:
                    resp = await http.get(
                        "https://generativelanguage.googleapis.com/v1beta/models",
                        params={"key": api_key},
                    )
                if resp.status_code == 200:
                    return True
            except (httpx.HTTPError, OSError):
                pass  # fall through to cliproxy probe
        # No api_key (or the api_key path failed) — try cliproxy. Empty
        # credential is the normal case after the cli_browser flow.
        from ai_accounts_core.cliproxy import cliproxy_list_models

        live = await cliproxy_list_models("gemini")
        return bool(live)

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # Gemini CLI 0.35+ has no `models list` subcommand. Two live sources:
        #   1. Google AI Studio's models endpoint with the API key — primary
        #      for api_key flows.
        #   2. CLIProxyAPI's /v1/models filtered by owned_by="google" — used
        #      when there's no api_key (OAuth-only registration via cliproxy).
        # Either is current; we pick whichever resolves first.
        api_key = credential.decode("utf-8", errors="replace").strip() if credential else ""
        if api_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as http:
                    resp = await http.get(
                        "https://generativelanguage.googleapis.com/v1beta/models",
                        params={"key": api_key},
                    )
                if resp.status_code == 200:
                    raw_data = resp.json()
                    items = raw_data.get("models", [])
                    if items:
                        return [
                            Model(
                                id=m.get("name", "").rsplit("/", 1)[-1],
                                display_name=m.get("displayName", m.get("name", "")),
                                context_window=m.get("inputTokenLimit"),
                            )
                            for m in items
                            if m.get("name")
                        ]
            except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError):
                pass  # fall through to cliproxy
        # No api_key, or Google API didn't respond — try cliproxy.
        from ai_accounts_core.cliproxy import cliproxy_list_models

        live = await cliproxy_list_models("gemini")
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

        return fallback("gemini")

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
        system_msgs = [m.content for m in request.messages if m.role == ChatRole.SYSTEM]
        if system_msgs:
            body["system_instruction"] = {"parts": [{"text": system_msgs[0]}]}
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{request.model}:streamGenerateContent?alt=sse&key={api_key}"
        )
        async with httpx.AsyncClient() as client, client.stream(
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
                        yield ChatStreamEvent(kind="token", payload=text)
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
            command=request.command,
            cols=request.cols,
            rows=request.rows,
            env=env,
        )

    def _env(self, credential: bytes, isolation_dir: Path) -> dict[str, str]:
        isolation_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, self._ISOLATION_ENV_VAR: str(isolation_dir)}
        if credential:
            env[self._API_KEY_ENV_VAR] = credential.decode()
        return env

    # _run() inherited from CliBackendBase.
