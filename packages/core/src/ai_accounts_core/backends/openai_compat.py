"""Generic OpenAI-compatible backend (base_url + api_key).

One backend that covers any OpenAI-shaped endpoint — Qwen, iFlow, Together,
Groq, DeepSeek, Mistral, etc. — by storing both the API key and the provider's
``base_url`` in the credential. There is no CLI to install: login is a two-step
api_key flow (base_url prompt, then key prompt) and the credential is JSON bytes
``{"api_key": ..., "base_url": ...}``.

``validate``/``list_models``/``chat`` decode that JSON, read ``base_url``, and
hit ``{base_url}/models`` and ``{base_url}/chat/completions`` (OpenAI shape —
same parsing as opencode). An empty/invalid base_url or a non-200 response fails
gracefully rather than raising.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar

import httpx

from ai_accounts_core.backends._base import CliBackendBase
from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    LoginSession,
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


def _decode_credential(credential: bytes) -> tuple[str, str]:
    """Return ``(base_url, api_key)`` from JSON credential bytes.

    Tolerant of empty/garbage input — returns empty strings so callers can
    fail gracefully (validate False, fallback models, chat error event).
    The base_url has any trailing slash stripped so callers can append
    ``/models`` / ``/chat/completions`` without double slashes.
    """
    if not credential:
        return "", ""
    try:
        raw = json.loads(credential.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError):
        return "", ""
    if not isinstance(raw, dict):
        return "", ""
    base_url = str(raw.get("base_url") or "").strip().rstrip("/")
    api_key = str(raw.get("api_key") or "").strip()
    return base_url, api_key


class _OpenAiCompatApiKeySession(LoginSession):
    """Two-step api_key flow: prompt for base_url, then for the API key.

    Sequential TextPrompts are driven the same way gemini's
    ``_GeminiCliProxySession`` drives UrlPrompt → TextPrompt: each prompt is
    yielded, then the session blocks on the answer queue for the client's
    reply before yielding the next. The resulting credential is JSON bytes
    ``{"api_key": ..., "base_url": ...}``.
    """

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
        return "openai_compat"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def _next_answer(self) -> PromptAnswer | None:
        """Await the next client answer; None signals the flow already ended."""
        try:
            ans = await asyncio.wait_for(self._answers.get(), timeout=300)
        except TimeoutError:
            self._done = True
            return None
        return ans

    async def events(self) -> AsyncIterator[LoginEvent]:
        # Step 1 — base URL. The TextPrompt's `prompt` is the input label
        # rendered by LoginStream; point at the OpenAI /v1 convention.
        yield TextPrompt(
            prompt_id="base_url",
            prompt="Base URL of the OpenAI-compatible endpoint (e.g. https://.../v1)",
            hidden=False,
        )
        ans = await self._next_answer()
        if ans is None:
            yield LoginFailed(code="response_timeout", message="No response within 5 minutes")
            return
        if ans.prompt_id == "__cancel__":
            self._done = True
            yield LoginFailed(code="cancelled", message="Login cancelled")
            return
        base_url = (ans.answer or "").strip()
        if not base_url:
            self._done = True
            yield LoginFailed(code="invalid_base_url", message="Base URL cannot be empty")
            return

        # Step 2 — API key.
        yield TextPrompt(prompt_id="api_key", prompt="API key", hidden=True)
        ans = await self._next_answer()
        if ans is None:
            yield LoginFailed(code="response_timeout", message="No response within 5 minutes")
            return
        if ans.prompt_id == "__cancel__":
            self._done = True
            yield LoginFailed(code="cancelled", message="Login cancelled")
            return
        api_key = (ans.answer or "").strip()
        if not api_key:
            self._done = True
            yield LoginFailed(code="invalid_key", message="API key cannot be empty")
            return

        self._credential = json.dumps({"api_key": api_key, "base_url": base_url}).encode("utf-8")
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


class OpenAiCompatBackend(CliBackendBase):
    kind: ClassVar[str] = "openai_compat"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="openai_compat",
        display_name="OpenAI-compatible (Custom)",
        icon_url=None,
        # Keyless: no binary to probe. `true` exits 0 with no output; the
        # permissive regex lets the optional version parse no-op succeed.
        install_check=InstallCheck(command=["true"], version_regex=r"(\d+)?"),
        login_flows=[
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste a base URL and API key for any OpenAI-compatible endpoint",
                requires_inputs=[
                    InputSpec(
                        name="base_url",
                        label="Base URL",
                        kind="text",
                        placeholder="https://.../v1",
                    ),
                    InputSpec(name="api_key", label="API key", kind="secret"),
                ],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {"base_url": {"type": "string"}},
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
        if flow_kind == "api_key":
            return _OpenAiCompatApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    async def detect(self) -> DetectResult:
        # Keyless backend — nothing to install, always available.
        return DetectResult(installed=True)

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        base_url, api_key = _decode_credential(credential)
        if not base_url or not api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except (httpx.HTTPError, OSError):
            return False
        return resp.status_code == 200

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # Live discovery from the configured endpoint's /models — same
        # OpenAI {data: [{id, name, context_length, ...}]} shape as opencode.
        from ai_accounts_core.backends._models_fallback import fallback

        base_url, api_key = _decode_credential(credential)
        if not base_url:
            return fallback("openai_compat")
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
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
            pass
        return fallback("openai_compat")

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        return []  # OpenAI-compatible endpoints have no standard usage API

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        base_url, api_key = _decode_credential(credential)
        if not base_url:
            yield ChatStreamEvent(kind="error", payload="No base URL configured")
            return
        messages_payload = [{"role": m.role.value, "content": m.content} for m in request.messages]
        body: dict[str, object] = {
            "model": request.model,
            "messages": messages_payload,
            "stream": True,
        }
        if "max_tokens" in request.params:
            body["max_tokens"] = request.params["max_tokens"]
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=body,
                headers=headers,
                timeout=120.0,
            ) as resp,
        ):
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
            command=request.command,
            cols=request.cols,
            rows=request.rows,
            env=env,
        )

    def _env(self, credential: bytes, isolation_dir: Path) -> dict[str, str]:
        base_url, api_key = _decode_credential(credential)
        env = {**os.environ}
        if api_key:
            env["OPENAI_API_KEY"] = api_key
        if base_url:
            env["OPENAI_BASE_URL"] = base_url
        return env
