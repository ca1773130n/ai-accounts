"""Self-hosted Claude Code backend (custom base_url + manual model list).

Covers any Anthropic-compatible endpoint (LiteLLM, claude-code-router, a
corporate gateway, …) that ai-accounts should treat as just another Claude
Code account. There is no model-discovery API to rely on and no OAuth: login
is a prompt flow (base URL, optional key, manual model list) and the
credential is JSON bytes ``{"base_url", "api_key", "models", "config_path"}``.

The credential is the ONLY channel that reaches chat()/list_models()/pty() on
every code path (ChatService, scheduler, PtyService all pass the raw
isolation dir and never see backend.config), so everything chat needs is
baked into it at login time. ``chat`` speaks the Anthropic ``/v1/messages``
SSE shape against ``{base_url}``; ``list_models`` returns the manual list
(first entry is the default model used by all/compound modes); ``pty``
spawns with ANTHROPIC_BASE_URL + CLAUDE_CONFIG_DIR so the real claude CLI
talks to the self-hosted endpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar

import httpx

from ai_accounts_core.backends._base import CliBackendBase
from ai_accounts_core.backends._iso import resolved_iso
from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.domain.chat import ChatRole
from ai_accounts_core.domain.usage import UsageWindow
from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    LoginSession,
    MenuOption,
    MenuPrompt,
    PromptAnswer,
    TextPrompt,
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

_ANTHROPIC_VERSION = "2023-06-01"


def _parse_models(raw: str) -> list[dict[str, str]]:
    """Parse ``id`` / ``id=Display Name`` entries split on commas/newlines."""
    out: list[dict[str, str]] = []
    for entry in re.split(r"[,\n]", raw):
        entry = entry.strip()
        if not entry:
            continue
        mid, _, label = entry.partition("=")
        mid = mid.strip()
        if mid:
            out.append({"id": mid, "display_name": label.strip() or mid})
    return out


def _decode_credential(credential: bytes) -> tuple[str, str, list[dict[str, str]], str]:
    """Return ``(base_url, api_key, models, config_path)`` from JSON credential bytes.

    Tolerant of empty/garbage input — returns empty values so callers can fail
    gracefully (validate False, empty model list, chat error event). The
    base_url has any trailing slash stripped so callers can append
    ``/v1/messages`` without double slashes.
    """
    if not credential:
        return "", "", [], ""
    try:
        raw = json.loads(credential.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError):
        return "", "", [], ""
    if not isinstance(raw, dict):
        return "", "", [], ""
    base_url = str(raw.get("base_url") or "").strip().rstrip("/")
    api_key = str(raw.get("api_key") or "").strip()
    config_path = str(raw.get("config_path") or "").strip()
    models = [
        {"id": str(m["id"]), "display_name": str(m.get("display_name") or m["id"])}
        for m in raw.get("models") or []
        if isinstance(m, dict) and m.get("id")
    ]
    return base_url, api_key, models, config_path


def _auth_headers(api_key: str) -> dict[str, str]:
    """Both header styles when a key exists — self-hosted gateways vary
    between the native ``x-api-key`` and ``Authorization: Bearer``."""
    if not api_key:
        return {}
    return {"x-api-key": api_key, "Authorization": f"Bearer {api_key}"}


class _ClaudeCustomEndpointSession(LoginSession):
    """Prompt flow: base URL → auth menu → (API key) → manual model list.

    Sequential prompts are driven the same way ``_OpenAiCompatApiKeySession``
    drives its steps: each prompt is yielded, then the session blocks on the
    answer queue before yielding the next. ``config_path`` (typed into the
    wizard's config step) is captured from the draft backend's config into the
    credential so pty() can honor it — backend.config never reaches pty.
    """

    def __init__(self, config: dict[str, object]) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue(maxsize=1)
        self._done = False
        self._credential: bytes | None = None
        self._config_path = str(config.get("config_path") or "")

    @property
    def credential(self) -> bytes | None:
        return self._credential

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "claude_custom"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def _next_answer(self) -> PromptAnswer | None:
        """Await the next client answer; None signals a timeout."""
        try:
            return await asyncio.wait_for(self._answers.get(), timeout=300)
        except TimeoutError:
            return None

    def _abort(self, ans: PromptAnswer | None) -> LoginFailed:
        """Terminal event for a timed-out (None) or cancelled answer."""
        self._done = True
        if ans is None:
            return LoginFailed(code="response_timeout", message="No response within 5 minutes")
        return LoginFailed(code="cancelled", message="Login cancelled")

    async def events(self) -> AsyncIterator[LoginEvent]:
        # Step 0 — endpoint root. /v1 is appended by chat(), so strip it here
        # rather than asking the user to know the convention.
        yield TextPrompt(
            prompt_id="base_url",
            prompt="Base URL of the Anthropic-compatible endpoint (e.g. https://llm.example.com)",
            hidden=False,
        )
        ans = await self._next_answer()
        if ans is None or ans.prompt_id == "__cancel__":
            yield self._abort(ans)
            return
        base_url = (ans.answer or "").strip().rstrip("/")
        base_url = base_url.removesuffix("/v1")
        if not base_url.startswith(("http://", "https://")):
            self._done = True
            yield LoginFailed(
                code="invalid_base_url", message="Base URL must start with http:// or https://"
            )
            return

        # Step 1 — auth mode. The bundled LoginStream can't submit a blank
        # field, so keyless endpoints get a menu branch instead of an
        # optional key prompt.
        yield MenuPrompt(
            prompt_id="auth_mode",
            prompt="Authentication",
            options=(
                MenuOption(number=1, label="API key / token"),
                MenuOption(number=2, label="None (keyless endpoint)"),
            ),
        )
        ans = await self._next_answer()
        if ans is None or ans.prompt_id == "__cancel__":
            yield self._abort(ans)
            return
        api_key = ""
        if (ans.answer or "").strip() != "2":
            yield TextPrompt(prompt_id="api_key", prompt="API key / token", hidden=True)
            ans = await self._next_answer()
            if ans is None or ans.prompt_id == "__cancel__":
                yield self._abort(ans)
                return
            api_key = (ans.answer or "").strip()
            if not api_key:
                self._done = True
                yield LoginFailed(code="invalid_key", message="API key cannot be empty")
                return

        # Step 2 — manual model list; there is no discovery API to trust on a
        # self-hosted endpoint. First entry becomes the default model.
        yield TextPrompt(
            prompt_id="models",
            prompt=(
                "Models the endpoint serves, comma-separated, optionally id=Display Name "
                "(first is the default) — e.g. claude-sonnet-5=Sonnet 5, my-tuned-model"
            ),
            hidden=False,
        )
        ans = await self._next_answer()
        if ans is None or ans.prompt_id == "__cancel__":
            yield self._abort(ans)
            return
        models = _parse_models(ans.answer or "")
        if not models:
            self._done = True
            yield LoginFailed(code="invalid_models", message="At least one model id is required")
            return

        self._credential = json.dumps(
            {
                "base_url": base_url,
                "api_key": api_key,
                "models": models,
                "config_path": self._config_path,
            }
        ).encode("utf-8")
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


class ClaudeCustomBackend(CliBackendBase):
    kind: ClassVar[str] = "claude_custom"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="claude_custom",
        display_name="Claude Code (Self-hosted)",
        icon_url=None,
        # Chat is plain HTTP — no binary to probe. `true` exits 0; the
        # optional-int regex matches its empty output without error.
        install_check=InstallCheck(command=["true"], version_regex=r"(\d+)?"),
        login_flows=[
            LoginFlowSpec(
                kind="api_key",
                display_name="Endpoint + model list",
                description=(
                    "Point at a self-hosted Anthropic-compatible endpoint "
                    "and name the models it serves"
                ),
                requires_inputs=[
                    InputSpec(
                        name="base_url",
                        label="Base URL",
                        kind="text",
                        placeholder="https://llm.example.com",
                    ),
                    InputSpec(name="api_key", label="API key / token", kind="secret"),
                    InputSpec(
                        name="models",
                        label="Models (comma-separated, id=Display Name)",
                        kind="text",
                    ),
                ],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "config_path": {"type": "string"},
            },
        },
        supports_multi_account=True,
        isolation_env_var="CLAUDE_CONFIG_DIR",
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict[str, object],
        vault_ctx: dict[str, object],
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "api_key":
            return _ClaudeCustomEndpointSession(config)
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    async def detect(self) -> DetectResult:
        # Chat needs no local CLI; pty picks up `claude` from PATH if present.
        return DetectResult(installed=True)

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        # The key is OPTIONAL (keyless self-hosted endpoints are valid); only
        # base_url is required. /v1/models may be unimplemented on minimal
        # gateways, so fall back to a 1-token /v1/messages reachability probe.
        base_url, api_key, models, _ = _decode_credential(credential)
        if not base_url:
            return False
        headers = _auth_headers(api_key)
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(f"{base_url}/v1/models", headers=headers)
                if resp.status_code == 200:
                    return True
                if resp.status_code in (401, 403):
                    return False  # reachable but the key was rejected
                probe = await http.post(
                    f"{base_url}/v1/messages",
                    headers={
                        **headers,
                        "anthropic-version": _ANTHROPIC_VERSION,
                        "content-type": "application/json",
                    },
                    json={
                        "model": models[0]["id"] if models else "",
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                        "stream": False,
                    },
                )
        except (httpx.HTTPError, OSError):
            return False
        if probe.status_code in (401, 403):
            return False
        # 400/422 = the route exists and speaks Anthropic; the throwaway body
        # was rejected, which still proves a reachable, compatible server.
        return probe.status_code in (200, 400, 422)

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # Manual list from login — no discovery call. Order matters: the first
        # entry is the default model for the chat panel and all/compound modes.
        _, _, models, _ = _decode_credential(credential)
        return [Model(id=m["id"], display_name=m["display_name"]) for m in models]

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list[UsageWindow]:
        return []  # self-hosted endpoints have no standard usage API

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        base_url, api_key, _, _ = _decode_credential(credential)
        if not base_url:
            yield ChatStreamEvent(kind="error", payload="No base URL configured")
            return
        messages_payload = [
            {"role": m.role.value, "content": m.content}
            for m in request.messages
            if m.role != ChatRole.SYSTEM
        ]
        system_msgs = [m.content for m in request.messages if m.role == ChatRole.SYSTEM]
        body: dict[str, object] = {
            "model": request.model,
            "messages": messages_payload,
            "max_tokens": request.params.get("max_tokens", 4096),
            "stream": True,
        }
        if system_msgs:
            body["system"] = system_msgs[0]
        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                f"{base_url}/v1/messages",
                json=body,
                headers={
                    **_auth_headers(api_key),
                    "anthropic-version": _ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                timeout=120.0,
            ) as resp,
        ):
            if resp.status_code != 200:
                yield ChatStreamEvent(kind="error", payload=f"API error {resp.status_code}")
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except (json.JSONDecodeError, ValueError):
                    continue  # self-hosted endpoints emit odd keep-alives
                if data.get("type") == "content_block_delta":
                    text = data.get("delta", {}).get("text", "")
                    if text:
                        yield ChatStreamEvent(kind="token", payload=text)
                elif data.get("type") == "message_delta":
                    usage = data.get("usage", {})
                    yield ChatStreamEvent(
                        kind="done",
                        payload={
                            "finish_reason": data.get("delta", {}).get("stop_reason", "stop"),
                            "tokens_out": usage.get("output_tokens"),
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
        base_url, api_key, models, config_path = _decode_credential(credential)
        # PtyService passes the raw isolation dir and never sees backend.config,
        # so the user's custom CLAUDE_CONFIG_DIR rides in the credential.
        cfg_dir = Path(config_path).expanduser() if config_path else isolation_dir
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(resolved_iso(cfg_dir))}
        if base_url:
            env["ANTHROPIC_BASE_URL"] = base_url
        if api_key:
            # ponytail: x-api-key auth only; add ANTHROPIC_AUTH_TOKEN if a
            # bearer-only gateway shows up.
            env["ANTHROPIC_API_KEY"] = api_key
        if models:
            env["ANTHROPIC_MODEL"] = models[0]["id"]
        return env
