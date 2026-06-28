"""Aider (Aider-AI/aider) backend — PTY-primary coding-agent CLI.

Aider is an interactive REPL coding agent that routes every model through
LiteLLM, which reads ``<PROVIDER>_API_KEY`` from the process environment. It
has no OpenAI-shaped HTTP endpoint and no config-home env var, so this backend
is a hybrid of two existing patterns:

- **Auth** ≈ ``openrouter`` / ``openai_compat``: an api-key credential injected
  as an env var in ``_env``. Aider is provider-agnostic, so the credential is
  JSON ``{"provider", "api_key", "model"}`` and ``_env`` sets the matching
  ``<PROVIDER>_API_KEY``.
- **Interaction + install** ≈ ``opencode``: ``InstallCheck(["aider",
  "--version"])``, a real CLI on PATH, and a PTY via ``AsyncPtyHandle.spawn``.

Isolation: aider auto-loads the host user's ``~/.aider.conf.yml`` and ``~/.env``
unless overridden. There is no ``AIDER_HOME``; instead ``_env`` points ``HOME``
at the isolation dir so per-account config can't leak across accounts.
``chat()`` is a best-effort one-shot ``aider --message`` stdout scrape — PTY is
the natural interaction (aider serves no streaming token API).
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

# Curated provider list for the login menu. The env var name LiteLLM expects is
# derived generically as f"{provider.upper()}_API_KEY", which covers every
# entry here (ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, …).
_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("anthropic", "Anthropic (Claude)"),
    ("openai", "OpenAI (GPT)"),
    ("openrouter", "OpenRouter"),
    ("gemini", "Google Gemini"),
    ("deepseek", "DeepSeek"),
)


def _decode_credential(credential: bytes) -> tuple[str, str, str]:
    """Decode JSON ``{provider, api_key, model}``; tolerate malformed input."""
    try:
        data = json.loads(credential.decode("utf-8")) if credential else {}
    except (ValueError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return (
        str(data.get("provider") or ""),
        str(data.get("api_key") or ""),
        str(data.get("model") or ""),
    )


class _AiderApiKeySession(LoginSession):
    """Provider menu → hidden api_key → model → JSON credential.

    Driven the same way ``openai_compat``'s session drives its sequential
    prompts: each prompt is yielded, then the session blocks on the answer queue
    before yielding the next. The provider MenuPrompt's answer is the option
    number (1-based into ``_PROVIDERS``).
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
        return "aider"

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
        # Step 1 — provider menu. The answer is the 1-based option number.
        yield MenuPrompt(
            prompt_id="provider",
            prompt="Model provider",
            options=tuple(
                MenuOption(number=i + 1, label=label)
                for i, (_value, label) in enumerate(_PROVIDERS)
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
        if not 1 <= choice <= len(_PROVIDERS):
            choice = 1
        provider = _PROVIDERS[choice - 1][0]

        # Step 2 — API key.
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

        # Step 3 — default model (aider's --model alias, e.g. "sonnet").
        yield TextPrompt(
            prompt_id="model",
            prompt="Default model (aider alias, e.g. sonnet / gpt-4o)",
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


class AiderBackend(CliBackendBase):
    kind: ClassVar[str] = "aider"
    _CLI_NAME: ClassVar[str] = "aider"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="aider",
        display_name="Aider",
        icon_url=None,
        install_check=InstallCheck(
            command=["aider", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Pick a provider and paste its API key",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {"model": {"type": "string"}},
        },
        supports_multi_account=True,
        # No AIDER_HOME equivalent — isolation is via HOME in _env().
        isolation_env_var=None,
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict[str, object],
        vault_ctx: dict[str, object],
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "api_key":
            return _AiderApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    # detect() inherited from CliBackendBase — aider IS a real binary on PATH.

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        # Aider is provider-agnostic (a LiteLLM router), so there is no single
        # key-check endpoint. Treat a credential carrying both provider and key
        # as valid; the real auth check happens when chat()/pty() shells aider.
        provider, api_key, _model = _decode_credential(credential)
        return bool(provider and api_key)

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # No live models endpoint — aider's --list-models reads LiteLLM's static
        # registry. Return the curated fallback list.
        from ai_accounts_core.backends._models_fallback import fallback

        return fallback("aider")

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list[UsageWindow]:
        return []  # aider exposes no usage API

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        env = self._env(credential, isolation_dir)
        cwd = str(resolved_iso(isolation_dir))
        proc = await asyncio.create_subprocess_exec(
            "aider",
            "--model",
            request.model,
            "--no-git",
            "--yes",
            "--message",
            request.messages[-1].content,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )
        out, _ = await proc.communicate()
        yield ChatStreamEvent(kind="token", payload=out.decode("utf-8", "replace"))
        yield ChatStreamEvent(kind="done", payload={"model": request.model})
        # ponytail: PTY-primary; chat() is a one-shot stdout scrape, no token stream.

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
        provider, api_key, _model = _decode_credential(credential)
        env = {**os.environ, "HOME": str(iso)}
        if provider and api_key:
            env[f"{provider.upper()}_API_KEY"] = api_key
        return env

    # _run() inherited from CliBackendBase.
