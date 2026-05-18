from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import Backend, BackendCredential, DetectResult
from ai_accounts_core.domain.chat import ChatMessage, ChatSession
from ai_accounts_core.domain.onboarding import OnboardingState
from ai_accounts_core.domain.principal import Principal
from ai_accounts_core.domain.session import LiveSession
from ai_accounts_core.domain.usage import FallbackChainEntry, UsageWindow
from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
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
from ai_accounts_core.protocols.auth import RequestContext
from ai_accounts_core.protocols.backend import Model
from ai_accounts_core.protocols.storage import (
    BackendRepository,
    HistoryRepository,
    OnboardingRepository,
    SessionRepository,
    UsageRepository,
)
from ai_accounts_core.protocols.vault import VaultError, canonicalize_vault_context


class _FakeBackendRepo:
    def __init__(self) -> None:
        self._backends: dict[str, Backend] = {}
        self._creds: dict[str, BackendCredential] = {}

    async def create(self, backend: Backend) -> None:
        if backend.id in self._backends:
            raise ValueError(f"backend {backend.id} already exists")
        self._backends[backend.id] = backend

    async def get(self, backend_id: str) -> Backend | None:
        return self._backends.get(backend_id)

    async def list(self) -> list[Backend]:
        return list(self._backends.values())

    async def update(self, backend: Backend) -> None:
        if backend.id not in self._backends:
            raise KeyError(backend.id)
        self._backends[backend.id] = backend

    async def delete(self, backend_id: str) -> None:
        self._backends.pop(backend_id, None)
        self._creds.pop(backend_id, None)

    async def put_credential(self, credential: BackendCredential) -> None:
        self._creds[credential.backend_id] = credential

    async def get_credential(self, backend_id: str) -> BackendCredential | None:
        return self._creds.get(backend_id)

    async def delete_credential(self, backend_id: str) -> None:
        self._creds.pop(backend_id, None)


class _FakeSessionRepo:
    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}

    async def upsert(self, session: LiveSession) -> None:
        self._sessions[session.id] = session

    async def get(self, session_id: str) -> LiveSession | None:
        return self._sessions.get(session_id)

    async def list_active(self) -> list[LiveSession]:
        return [s for s in self._sessions.values() if s.state.value != "ended"]

    async def end(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class _FakeHistoryRepo:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._messages: dict[str, list[ChatMessage]] = defaultdict(list)

    async def create_session(self, session: ChatSession) -> None:
        self._sessions[session.id] = session

    async def append_message(self, message: ChatMessage) -> None:
        self._messages[message.session_id].append(message)

    async def list_messages(self, session_id: str) -> list[ChatMessage]:
        return list(self._messages[session_id])

    async def list_sessions(self, backend_id: str | None = None) -> list[ChatSession]:
        sessions = list(self._sessions.values())
        if backend_id is not None:
            sessions = [s for s in sessions if s.backend_id == backend_id]
        return sessions


class _FakeOnboardingRepo:
    def __init__(self) -> None:
        self._states: dict[str, OnboardingState] = {}

    async def get(self, onboarding_id: str) -> OnboardingState | None:
        return self._states.get(onboarding_id)

    async def put(self, state: OnboardingState) -> None:
        self._states[state.id] = state


class _FakeUsageRepo:
    def __init__(self) -> None:
        self._snapshots: dict[str, list[UsageWindow]] = defaultdict(list)
        self._rate_limits: dict[str, tuple[datetime, str]] = {}
        self._last_used: dict[str, datetime] = {}
        self._last_polled: dict[str, datetime] = {}
        self._chain: list[FallbackChainEntry] = []

    async def put_snapshot(self, backend_id: str, windows: list[UsageWindow]) -> None:
        self._snapshots[backend_id] = list(windows) + self._snapshots[backend_id]

    async def get_latest_snapshots(self, backend_id: str) -> list[UsageWindow]:
        seen: set[str] = set()
        result: list[UsageWindow] = []
        for w in self._snapshots.get(backend_id, []):
            if w.window_type in seen:
                continue
            seen.add(w.window_type)
            result.append(w)
        return result

    async def set_rate_limited(self, backend_id: str, until: datetime, reason: str) -> None:
        self._rate_limits[backend_id] = (until, reason)

    async def clear_rate_limited(self, backend_id: str) -> None:
        self._rate_limits.pop(backend_id, None)

    async def get_rate_limit_state(self, backend_id: str) -> tuple[datetime | None, str | None]:
        entry = self._rate_limits.get(backend_id)
        if entry is None:
            return (None, None)
        return entry

    async def set_last_used(self, backend_id: str, at: datetime) -> None:
        self._last_used[backend_id] = at

    async def set_last_polled(self, backend_id: str, at: datetime) -> None:
        self._last_polled[backend_id] = at

    async def set_chain(self, entries: list[FallbackChainEntry]) -> None:
        self._chain = list(entries)

    async def get_chain(self) -> list[FallbackChainEntry]:
        return sorted(self._chain, key=lambda e: e.priority)


class FakeStorage:
    def __init__(self) -> None:
        self._backends = _FakeBackendRepo()
        self._sessions = _FakeSessionRepo()
        self._history = _FakeHistoryRepo()
        self._onboarding = _FakeOnboardingRepo()
        self._usage = _FakeUsageRepo()

    async def backends(self) -> BackendRepository:
        return self._backends

    async def sessions(self) -> SessionRepository:
        return self._sessions

    async def history(self) -> HistoryRepository:
        return self._history

    async def onboarding(self) -> OnboardingRepository:
        return self._onboarding

    async def usage(self) -> UsageRepository:
        return self._usage

    async def migrate(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeVault:
    """Test-only vault. Stores plaintext inside the envelope — DO NOT use outside tests."""

    def __init__(self, key_id: str = "fake://v1") -> None:
        self._key_id = key_id

    async def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> bytes:
        ctx = canonicalize_vault_context(context)
        payload = b"ENC|" + ctx + b"||" + plaintext
        digest = hashlib.sha256(payload).digest()
        return payload + digest

    async def decrypt(self, ciphertext: bytes, *, context: dict[str, str]) -> bytes:
        if len(ciphertext) < 32 + 4:
            raise VaultError("truncated")
        payload, digest = ciphertext[:-32], ciphertext[-32:]
        if hashlib.sha256(payload).digest() != digest:
            raise VaultError("tamper detected")
        if not payload.startswith(b"ENC|"):
            raise VaultError("not a FakeVault envelope")
        body = payload[4:]
        expected_ctx = canonicalize_vault_context(context)
        if not body.startswith(expected_ctx + b"||"):
            raise VaultError("context mismatch")
        return body[len(expected_ctx) + 2 :]

    async def current_key_id(self) -> str:
        return self._key_id

    async def rotate(self, old_key_id: str) -> None:
        return None


class FakeAuth:
    def __init__(self, principal: Principal | None = None) -> None:
        self._principal = principal or Principal(id="fake:anon", display_name="Anon")

    async def authenticate(self, request: RequestContext) -> Principal | None:
        return self._principal


class _FakeLoginSession(LoginSession):
    def __init__(self, flow_kind: str) -> None:
        import uuid

        self._flow_kind = flow_kind
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
        self._done = False
        self._sid = f"sess-fake-{uuid.uuid4().hex[:8]}"
        self._credential: bytes | None = None

    @property
    def credential(self) -> bytes | None:
        return self._credential

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "fake"

    @property
    def flow_kind(self) -> str:
        return self._flow_kind

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        if self._flow_kind == "api_key":
            yield TextPrompt(prompt_id="key", prompt="API key:", hidden=True)
            ans = await self._answers.get()
            self._credential = ans.answer.encode("utf-8")
        yield LoginComplete(account_id="bkd-fake", backend_status="validating")
        self._done = True

    async def respond(self, answer: PromptAnswer) -> None:
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True


class FakeBackend:
    kind: ClassVar[str] = "fake"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key", "oauth_device"})
    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="fake",
        display_name="Fake",
        icon_url=None,
        install_check=InstallCheck(command=["fake", "--version"], version_regex=r"(\d+)"),
        login_flows=[
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste your fake API key",
                requires_inputs=[InputSpec(name="key", label="Key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={"type": "object"},
        supports_multi_account=True,
        isolation_env_var=None,
    )

    def __init__(self, *, tool_call: dict | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._tool_call = tool_call

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        self.calls.append(("begin_login", flow_kind))
        return _FakeLoginSession(flow_kind)

    async def detect(self) -> DetectResult:
        self.calls.append(("detect", None))
        return DetectResult(installed=True, version="fake/0.0", path="/usr/local/bin/fake")

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        self.calls.append(("validate", credential))
        if credential == b"fake-credential":
            return True
        if credential.startswith(b"sk-fake") or credential.startswith(b"fake"):
            return True
        if credential == b"" and (isolation_dir / "oauth_token.fake").exists():
            return True
        return False

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        self.calls.append(("list_models", credential))
        return [Model(id="fake-1", display_name="Fake Model 1")]

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        from ai_accounts_core.domain.usage import UsageWindow

        self.calls.append(("get_usage", credential))
        return [UsageWindow(window_type="five_hour", usage_percent=25.0, resets_at=None)]

    async def chat(  # type: ignore[override]
        self,
        request: Any,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[Any]:
        from ai_accounts_core.protocols.backend import ChatStreamEvent

        self.calls.append(("chat", request))
        if self._tool_call is not None:
            yield ChatStreamEvent(kind="tool_call", payload=self._tool_call)
        yield ChatStreamEvent(kind="token", payload="Hello ")
        yield ChatStreamEvent(kind="token", payload="world!")
        yield ChatStreamEvent(
            kind="done", payload={"tokens_in": 10, "tokens_out": 2, "model": "fake-1"}
        )

    async def pty(  # type: ignore[override]
        self,
        request: Any,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> Any:
        from ai_accounts_core.pty.handle import AsyncPtyHandle

        self.calls.append(("pty", request))
        cmd = request.command if hasattr(request, "command") else ("/bin/sh",)
        cols = request.cols if hasattr(request, "cols") else 80
        rows = request.rows if hasattr(request, "rows") else 24
        return await AsyncPtyHandle.spawn(command=cmd, cols=cols, rows=rows)
