"""Qwen (Alibaba DashScope) backend — OpenAI-compatible api-key.

Thin named-provider wrapper modelled on ``openrouter.py`` but with a region
selector. Qwen Code's public surface is the DashScope / ModelStudio
OpenAI-compatible endpoint, which differs only by region host. Login first
emits a :class:`MenuPrompt` (China / International / Custom), resolves the
``base_url``, then prompts for the DashScope API key. The credential is JSON
bytes ``{"api_key": ..., "base_url": ...}`` (same shape as ``openai_compat``)
so ``validate``/``list_models``/``chat`` decode it via
``openai_compat._decode_credential``.
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
from ai_accounts_core.backends.openai_compat import _decode_credential
from ai_accounts_core.domain.backend import DetectResult
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

# DashScope OpenAI-compatible bases per region (compatible-mode/v1).
_QWEN_CN_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_QWEN_INTL_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
_QWEN_BASE = _QWEN_CN_BASE  # default when a credential omits base_url


class _QwenApiKeySession(LoginSession):
    """Region menu → (optional custom base_url) → api_key → JSON credential.

    Prompts are driven the same way ``openai_compat``'s session drives its
    sequential TextPrompts: each prompt is yielded, then the session blocks on
    the answer queue before yielding the next. The region MenuPrompt's answer
    is the option ``number`` (1=China, 2=International, 3=Custom).
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
        return "qwen"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def _next_answer(self) -> PromptAnswer | None:
        """Await the next client answer; None signals the flow already ended."""
        try:
            return await asyncio.wait_for(self._answers.get(), timeout=300)
        except TimeoutError:
            self._done = True
            return None

    async def events(self) -> AsyncIterator[LoginEvent]:
        # Step 1 — region menu. The answer is the option number (1/2/3).
        yield MenuPrompt(
            prompt_id="region",
            prompt="DashScope region",
            options=(
                MenuOption(number=1, label="China (dashscope.aliyuncs.com)"),
                MenuOption(number=2, label="International (dashscope-intl)"),
                MenuOption(number=3, label="Custom base URL"),
            ),
        )
        ans = await self._next_answer()
        if ans is None:
            yield LoginFailed(code="response_timeout", message="No response within 5 minutes")
            return
        if ans.prompt_id == "__cancel__":
            self._done = True
            yield LoginFailed(code="cancelled", message="Login cancelled")
            return
        try:
            choice = int((ans.answer or "").strip())
        except ValueError:
            choice = 1

        base_url = ""
        if choice == 2:
            base_url = _QWEN_INTL_BASE
        elif choice == 3:
            # Step 2 (custom only) — follow-up base_url prompt.
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
        else:
            base_url = _QWEN_CN_BASE

        # Step 3 — API key.
        yield TextPrompt(prompt_id="api_key", prompt="DashScope API key", hidden=True)
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


class QwenBackend(CliBackendBase):
    kind: ClassVar[str] = "qwen"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="qwen",
        display_name="Qwen (Alibaba DashScope)",
        icon_url=None,
        # Keyless backend — no CLI binary to probe. `true` always exits 0;
        # the optional-int regex matches its empty output without error.
        install_check=InstallCheck(
            command=["true"],
            version_regex=r"(\d+)?",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Pick a DashScope region and paste an API key",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
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
            return _QwenApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    async def detect(self) -> DetectResult:
        # Keyless: nothing to install, so report available without shelling a
        # binary (CliBackendBase.detect would `shutil.which` an absent CLI).
        return DetectResult(installed=True)

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        base_url, api_key = _decode_credential(credential)
        base_url = base_url or _QWEN_BASE
        if not api_key:
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
        # Live discovery from DashScope's /models — same OpenAI
        # {data: [{id, name, context_length, ...}]} shape as openai_compat.
        from ai_accounts_core.backends._models_fallback import fallback

        base_url, api_key = _decode_credential(credential)
        base_url = base_url or _QWEN_BASE
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
        return fallback("qwen")

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        return []  # DashScope's OpenAI-compatible surface has no usage API

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        base_url, api_key = _decode_credential(credential)
        base_url = base_url or _QWEN_BASE
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
            env["DASHSCOPE_API_KEY"] = api_key
        if base_url:
            env["OPENAI_BASE_URL"] = base_url
        return env
