from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ai_accounts_core.domain.backend import Backend, BackendCredential, DetectResult
from ai_accounts_core.domain.chat import ChatMessage, ChatSession
from ai_accounts_core.domain.onboarding import OnboardingState
from ai_accounts_core.domain.principal import Principal
from ai_accounts_core.domain.session import LiveSession
from ai_accounts_core.protocols.auth import RequestContext
from ai_accounts_core.protocols.backend import (
    CredentialLogin,
    LoginError,
    LoginFlow,
    LoginResult,
    Model,
    OAuthDeviceLogin,
)
from ai_accounts_core.protocols.storage import (
    BackendRepository,
    HistoryRepository,
    OnboardingRepository,
    SessionRepository,
    StorageProtocol,
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


class FakeStorage:
    def __init__(self) -> None:
        self._backends = _FakeBackendRepo()
        self._sessions = _FakeSessionRepo()
        self._history = _FakeHistoryRepo()
        self._onboarding = _FakeOnboardingRepo()

    async def backends(self) -> BackendRepository:
        return self._backends

    async def sessions(self) -> SessionRepository:
        return self._sessions

    async def history(self) -> HistoryRepository:
        return self._history

    async def onboarding(self) -> OnboardingRepository:
        return self._onboarding

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


class FakeBackend:
    kind = "fake"
    supported_login_flows: frozenset[str] = frozenset({"api_key", "oauth_device"})

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._oauth_poll_counts: dict[str, int] = {}

    async def detect(self) -> DetectResult:
        self.calls.append(("detect", None))
        return DetectResult(installed=True, version="fake/0.0", path="/usr/local/bin/fake")

    async def login(self, flow: LoginFlow, *, isolation_dir: Path) -> LoginResult:
        self.calls.append(("login", flow))
        if flow.kind == "api_key":
            return CredentialLogin(credential=b"fake-credential")
        if flow.kind == "oauth_device":
            handle = f"fake-handle-{len(self._oauth_poll_counts)}"
            self._oauth_poll_counts[handle] = 0
            return OAuthDeviceLogin(
                verification_uri="https://example.com/device",
                user_code="FAKE-1234",
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
                handle=handle,
            )
        return LoginError(
            code="unsupported_flow",
            message=f"FakeBackend does not support {flow.kind!r}",
        )

    async def poll_login(self, handle: str, *, isolation_dir: Path) -> LoginResult:
        self.calls.append(("poll_login", handle))
        if handle not in self._oauth_poll_counts:
            return LoginError(code="unknown_handle", message=handle)
        self._oauth_poll_counts[handle] += 1
        if self._oauth_poll_counts[handle] >= 2:
            isolation_dir.mkdir(parents=True, exist_ok=True)
            (isolation_dir / "oauth_token.fake").write_text("logged-in")
            return CredentialLogin(credential=b"")
        return OAuthDeviceLogin(
            verification_uri="https://example.com/device",
            user_code="FAKE-1234",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            handle=handle,
        )

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        self.calls.append(("validate", credential))
        if credential == b"fake-credential":
            return True
        if credential == b"" and (isolation_dir / "oauth_token.fake").exists():
            return True
        return False

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]:
        self.calls.append(("list_models", credential))
        return [Model(id="fake-1", display_name="Fake Model 1")]

    async def chat(self, request: object, credential: bytes, *, isolation_dir: Path):  # type: ignore[no-untyped-def]
        raise NotImplementedError("chat lands in Phase 3")

    async def pty(self, request: object, credential: bytes, *, isolation_dir: Path):  # type: ignore[no-untyped-def]
        raise NotImplementedError("pty lands in Phase 4")
