"""Goose (Block) backend — PTY-primary CLI agent over a bring-your-own provider.

Goose is an on-machine agentic CLI (``goose session`` TUI, ``goose run``
headless) that drives *any* provider you configure — it is not its own
identity. Modelled on ``opencode.py`` (``CliBackendBase`` + config-dir
isolation + interactive PTY), but auth is provider-key shaped like
``openai_compat``: the credential is JSON bytes ``{"provider", "api_key",
"model"}``.

Isolation: ``GOOSE_PATH_ROOT`` overrides config/data/state, but Goose's
secrets default to the *shared system keyring* which ``GOOSE_PATH_ROOT`` does
NOT scope — so ``_env`` also forces ``GOOSE_DISABLE_KEYRING=true`` to keep
each account's ``secrets.yaml`` under its isolated root.

There is no stable HTTP chat endpoint and no ``models list`` command, so
``chat()`` drives ``goose run --output-format stream-json`` as a subprocess
and parses stdout, and ``list_models()`` reports the configured model. ``pty()``
(``goose session``) is the primary, lowest-risk surface.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar

from ai_accounts_core.backends._base import CliBackendBase
from ai_accounts_core.backends._iso import resolved_iso
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

# (key, label) — providers Goose can front with a single api_key env var.
# Order is presentation order; the 1-based menu number maps into it.
_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("anthropic", "Anthropic (Claude)"),
    ("openai", "OpenAI"),
    ("openrouter", "OpenRouter"),
)

# provider → the per-provider API-key env var Goose reads.
_PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _decode_goose_credential(credential: bytes) -> tuple[str, str, str]:
    """Return ``(provider, api_key, model)`` from JSON credential bytes.

    Tolerant of empty/garbage input — returns empty strings so callers can
    fail gracefully (validate False, fallback models).
    """
    if not credential:
        return "", "", ""
    try:
        raw = json.loads(credential.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError):
        return "", "", ""
    if not isinstance(raw, dict):
        return "", "", ""
    provider = str(raw.get("provider") or "").strip()
    api_key = str(raw.get("api_key") or "").strip()
    model = str(raw.get("model") or "").strip()
    return provider, api_key, model


class _GooseApiKeySession(LoginSession):
    """provider menu → api_key → model → JSON credential.

    Prompts are driven the same way ``openai_compat``'s session drives its
    sequential prompts: each prompt is yielded, then the session blocks on the
    answer queue before yielding the next. The provider MenuPrompt's answer is
    the option ``number`` (1=Anthropic, 2=OpenAI, 3=OpenRouter).
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
        return "goose"

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
        # Step 1 — provider menu. The answer is the option number (1/2/3).
        yield MenuPrompt(
            prompt_id="provider",
            prompt="Provider",
            options=tuple(
                MenuOption(number=i + 1, label=label) for i, (_key, label) in enumerate(_PROVIDERS)
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
            idx = int((ans.answer or "").strip()) - 1
        except ValueError:
            idx = 0
        if not 0 <= idx < len(_PROVIDERS):
            idx = 0
        provider = _PROVIDERS[idx][0]

        # Step 2 — provider API key.
        yield TextPrompt(prompt_id="api_key", prompt=f"{provider} API key", hidden=True)
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

        # Step 3 — model id (provider-defined; Goose has no models-list command).
        yield TextPrompt(
            prompt_id="model",
            prompt="Model id (e.g. claude-sonnet-4-5)",
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
        model = (ans.answer or "").strip()
        if not model:
            self._done = True
            yield LoginFailed(code="invalid_model", message="Model cannot be empty")
            return

        self._credential = json.dumps(
            {"provider": provider, "api_key": api_key, "model": model}
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


class GooseBackend(CliBackendBase):
    kind: ClassVar[str] = "goose"
    _CLI_NAME: ClassVar[str] = "goose"
    _ISOLATION_ENV_VAR: ClassVar[str] = "GOOSE_PATH_ROOT"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="goose",
        display_name="Goose",
        icon_url=None,
        install_check=InstallCheck(
            command=["goose", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Pick a provider and paste its API key + model id",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {"model": {"type": "string"}},
        },
        supports_multi_account=True,
        isolation_env_var="GOOSE_PATH_ROOT",
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict[str, object],
        vault_ctx: dict[str, object],
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "api_key":
            return _GooseApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    # detect() inherited from CliBackendBase.

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        # Goose has no key-check subcommand; `goose info` resolves config under
        # the isolated env and exits 0 when provider/model are set. We first
        # require a complete credential so an incomplete JSON fails fast.
        provider, api_key, model = _decode_goose_credential(credential)
        if not (provider and api_key and model):
            return False
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return False
        iso = resolved_iso(isolation_dir)
        env = self._env(credential, iso)
        rc, _stdout, _stderr = await self._run({"argv": [path, "info"], "env": env})
        return rc == 0

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # Goose exposes no machine-readable models-list command and no stable
        # HTTP surface — models are provider-defined. Surface the model the
        # account was configured with so the chat UI/all-mode has a selectable
        # entry; fall back to the cached cliproxy snapshot otherwise.
        from ai_accounts_core.backends._models_fallback import fallback

        _provider, _api_key, model = _decode_goose_credential(credential)
        if model:
            return [Model(id=model, display_name=model)]
        return fallback("goose")

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list[UsageWindow]:
        return []  # Goose has no usage API

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        if not request.messages:
            yield ChatStreamEvent(kind="error", payload="no messages provided")
            return
        env = self._env(credential, isolation_dir)
        proc = await asyncio.create_subprocess_exec(
            "goose",
            "run",
            "-t",
            request.messages[-1].content,
            "--no-session",
            "--output-format",
            "stream-json",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            text = ev.get("content") or ev.get("text") if isinstance(ev, dict) else None
            if isinstance(text, str) and text:
                yield ChatStreamEvent(kind="token", payload=text)
        await proc.wait()
        yield ChatStreamEvent(kind="done", payload={"model": request.model})
        # ponytail: chat() parses `goose run` stream-json; pty() is the fallback if framing shifts.

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
        iso = isolation_dir.resolve()
        iso.mkdir(parents=True, exist_ok=True)
        provider, api_key, model = _decode_goose_credential(credential)
        env = {
            **os.environ,
            self._ISOLATION_ENV_VAR: str(iso),
            # GOOSE_PATH_ROOT does NOT scope the system keyring — force plaintext
            # secrets.yaml under the isolated root for true per-account isolation.
            "GOOSE_DISABLE_KEYRING": "true",
        }
        if provider:
            env["GOOSE_PROVIDER"] = provider
        if model:
            env["GOOSE_MODEL"] = model
        if api_key:
            env[_PROVIDER_KEY_ENV.get(provider, f"{provider.upper()}_API_KEY")] = api_key
        return env

    # _run() inherited from CliBackendBase.
