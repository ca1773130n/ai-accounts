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

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class _OpenRouterApiKeySession(LoginSession):
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
        return "openrouter"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="api_key", prompt="OpenRouter API key", hidden=True)
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


class OpenRouterBackend(CliBackendBase):
    kind: ClassVar[str] = "openrouter"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="openrouter",
        display_name="OpenRouter",
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
                description="Paste an OpenRouter API key",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {"email": {"type": "string"}},
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
            return _OpenRouterApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    async def detect(self) -> DetectResult:
        # Keyless: nothing to install, so report available without shelling a
        # binary (CliBackendBase.detect would `shutil.which` an absent CLI).
        return DetectResult(installed=True)

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        # A valid OpenRouter key authenticates against the public /models
        # endpoint (sends the key for parity with chat()).
        api_key = credential.decode("utf-8", errors="replace").strip() if credential else ""
        if not api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    f"{_OPENROUTER_BASE}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except (httpx.HTTPError, OSError):
            return False
        return resp.status_code == 200

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # Live discovery from OpenRouter. /v1/models is publicly readable; the
        # api_key is sent for parity with chat(). Returns OpenAI-style
        # {data: [{id, name, context_length, ...}]}.
        api_key = credential.decode("utf-8", errors="replace").strip() if credential else ""
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    f"{_OPENROUTER_BASE}/models",
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
        from ai_accounts_core.backends._models_fallback import fallback

        return fallback("openrouter")

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
        messages_payload = [{"role": m.role.value, "content": m.content} for m in request.messages]
        body: dict[str, object] = {
            "model": request.model,
            "messages": messages_payload,
            "stream": True,
        }
        if "max_tokens" in request.params:
            body["max_tokens"] = request.params["max_tokens"]
        async with (
            httpx.AsyncClient() as client,
            client.stream(
                "POST",
                f"{_OPENROUTER_BASE}/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
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
        return {
            **os.environ,
            "OPENROUTER_API_KEY": credential.decode(),
        }
