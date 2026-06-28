"""Crush (charmbracelet/crush) backend — PTY-first agentic coding CLI.

Structurally modelled on ``opencode.py`` (a Go/TUI CLI wrapped with config/data
dir isolation), but auth is per-provider API key (like ``openai_compat`` /
``openrouter``) rather than an OAuth browser flow. Login collects a provider, an
API key and an optional model, then writes an isolated ``crush.json`` under the
isolation dir instead of driving Crush's TUI login prompt — this sidesteps the
open question of whether the TUI persists the key into the config vs the data
dir (see research note).

Isolation uses Crush's two override env vars:

- ``CRUSH_GLOBAL_CONFIG`` → ``<iso>/crush.json`` (the global config file)
- ``CRUSH_GLOBAL_DATA``   → ``<iso>/data`` (state / DB / logs)

Crush is TUI-only for interactive use; ``crush run`` exists but emits plain
assistant text on stdout with no structured/JSON stream. We therefore expose the
TUI via :meth:`pty` and make :meth:`chat` yield an ``error`` event.
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

_CRUSH_SCHEMA = "https://charm.land/crush.json"

# Well-known providers offered by the login menu, in display order. Each entry
# is (id, display name, crush provider "type", base_url). base_url + type are
# what Crush needs to talk to an OpenAI-/Anthropic-compatible endpoint.
_CRUSH_PROVIDERS: tuple[tuple[str, str, str, str], ...] = (
    ("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com/v1"),
    ("openai", "OpenAI", "openai", "https://api.openai.com/v1"),
    ("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1"),
    ("groq", "Groq", "openai", "https://api.groq.com/openai/v1"),
)


def _provider_meta(provider_id: str) -> tuple[str, str, str, str]:
    """Resolve a provider id to (id, name, type, base_url); unknown → openai shape."""
    for entry in _CRUSH_PROVIDERS:
        if entry[0] == provider_id:
            return entry
    return (provider_id, provider_id, "openai", "")


def _build_crush_config(provider_id: str, api_key: str, model: str) -> dict[str, object]:
    """Build a minimal isolated crush.json declaring one provider + api_key."""
    pid, name, ptype, base_url = _provider_meta(provider_id)
    block: dict[str, object] = {"id": pid, "name": name, "type": ptype, "api_key": api_key}
    if base_url:
        block["base_url"] = base_url
    if model:
        block["models"] = [{"id": model, "name": model}]
    return {"$schema": _CRUSH_SCHEMA, "providers": {pid: block}}


def _write_crush_config(isolation_dir: Path, provider_id: str, api_key: str, model: str) -> Path:
    """Write ``<iso>/crush.json`` (absolute) and return its path."""
    iso = resolved_iso(isolation_dir)
    config_path = iso / "crush.json"
    config_path.write_text(json.dumps(_build_crush_config(provider_id, api_key, model), indent=2))
    config_path.chmod(0o600)
    return config_path


def _decode_credential(credential: bytes) -> tuple[str, str, str]:
    """Decode the JSON credential into (provider, api_key, model)."""
    try:
        data = json.loads(credential.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ("", "", "")
    if not isinstance(data, dict):
        return ("", "", "")
    return (
        str(data.get("provider") or ""),
        str(data.get("api_key") or ""),
        str(data.get("model") or ""),
    )


class _CrushApiKeySession(LoginSession):
    """Provider menu → api_key → (optional) model → isolated crush.json.

    Prompts are driven the same way ``openai_compat`` drives sequential
    prompts: each prompt is yielded, then the session blocks on the answer queue
    before yielding the next. The provider MenuPrompt's answer is the option
    number (1-based, indexing ``_CRUSH_PROVIDERS``).
    """

    def __init__(self, isolation_dir: Path) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._isolation_dir = isolation_dir
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
        return "crush"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def _next_answer(self) -> PromptAnswer | None:
        """Await the next client answer; None signals timeout / flow end."""
        try:
            return await asyncio.wait_for(self._answers.get(), timeout=300)
        except TimeoutError:
            self._done = True
            return None

    async def events(self) -> AsyncIterator[LoginEvent]:
        # Step 1 — provider menu. Answer is the 1-based option number.
        yield MenuPrompt(
            prompt_id="provider",
            prompt="Model provider",
            options=tuple(
                MenuOption(number=i + 1, label=name)
                for i, (_pid, name, _t, _b) in enumerate(_CRUSH_PROVIDERS)
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
        if not (0 <= idx < len(_CRUSH_PROVIDERS)):
            idx = 0
        provider_id, provider_name, _type, _base = _CRUSH_PROVIDERS[idx]

        # Step 2 — API key (hidden).
        yield TextPrompt(prompt_id="api_key", prompt=f"{provider_name} API key", hidden=True)
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

        # Step 3 — optional model id (e.g. claude-sonnet-4-5). Blank is allowed.
        yield TextPrompt(
            prompt_id="model",
            prompt="Model id (e.g. claude-sonnet-4-5), or leave blank",
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

        # Persist the isolated crush.json ourselves (no TUI login).
        _write_crush_config(self._isolation_dir, provider_id, api_key, model)
        self._credential = json.dumps(
            {"provider": provider_id, "api_key": api_key, "model": model}
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


class CrushBackend(CliBackendBase):
    kind: ClassVar[str] = "crush"
    _CLI_NAME: ClassVar[str] = "crush"
    _ISOLATION_ENV_VAR: ClassVar[str] = "CRUSH_GLOBAL_CONFIG"
    _DATA_ENV_VAR: ClassVar[str] = "CRUSH_GLOBAL_DATA"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="crush",
        display_name="Crush",
        icon_url=None,
        install_check=InstallCheck(
            command=["crush", "--version"],
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
            "properties": {"provider": {"type": "string"}, "model": {"type": "string"}},
        },
        supports_multi_account=True,
        isolation_env_var="CRUSH_GLOBAL_CONFIG",
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict[str, object],
        vault_ctx: dict[str, object],
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "api_key":
            return _CrushApiKeySession(isolation_dir)
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    # detect() inherited from CliBackendBase (shells `crush --version`).

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        # No cheap network probe (Crush has no machine-readable auth check) — a
        # decodable credential with a non-empty api_key is treated as valid.
        _provider, api_key, _model = _decode_credential(credential)
        return bool(api_key)

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        # No first-class `crush models --json`; live enumeration would require
        # parsing the Catwalk catalog. Fall back to the shipped static set.
        from ai_accounts_core.backends._models_fallback import fallback

        return fallback("crush")

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list[UsageWindow]:
        return []

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        # ponytail: crush is TUI-only; no structured headless stream — pty() only.
        yield ChatStreamEvent(
            kind="error",
            payload="crush is TUI-only; use an interactive PTY session",
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
            cwd=str(resolved_iso(isolation_dir)),
        )

    def _env(self, credential: bytes, isolation_dir: Path) -> dict[str, str]:
        iso = resolved_iso(isolation_dir)
        provider, api_key, model = _decode_credential(credential)
        # (Re)write the isolated config from the credential so a PTY session
        # works even after a credential restore with no fresh login.
        config_path = _write_crush_config(iso, provider, api_key, model)
        data_dir = iso / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return {
            **os.environ,
            self._ISOLATION_ENV_VAR: str(config_path),
            self._DATA_ENV_VAR: str(data_dir),
        }
