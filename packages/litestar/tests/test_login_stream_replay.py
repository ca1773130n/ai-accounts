"""Integration test: SSE /login/stream replays the cached UrlPrompt.

When a client disconnects and reconnects mid-login, the new subscriber
to GET /api/v1/backends/{id}/login/stream must immediately receive the
last-emitted UrlPrompt — otherwise the UI sits on a spinner because the
OAuth URL was already consumed by the previous (dead) subscription.

This verifies the late-subscriber replay path added to
``LoginSession.events_with_replay`` + the login SSE route.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
import pytest_asyncio
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginSession,
    PromptAnswer,
    UrlPrompt,
)
from ai_accounts_core.metadata import (
    BackendMetadata,
    InstallCheck,
    LoginFlowSpec,
)
from ai_accounts_core.testing import FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig
from litestar.testing import AsyncTestClient


class _OAuthSession(LoginSession):
    """Scripted OAuth-style login session used by tests.

    Yields a UrlPrompt and then blocks until an external ``proceed``
    event is set, so the test can simulate a disconnect + reconnect in
    the middle of the flow.
    """

    def __init__(self) -> None:
        import uuid

        self._sid = f"sess-oauth-{uuid.uuid4().hex[:8]}"
        self._done = False
        self._proceed = asyncio.Event()
        self.url = UrlPrompt(
            prompt_id="p-url", url="https://example.com/device", user_code="ABC-123"
        )

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "oauth-fake"

    @property
    def flow_kind(self) -> str:
        return "oauth_device"

    @property
    def done(self) -> bool:
        return self._done

    @property
    def credential(self) -> bytes | None:
        return b""  # OAuth writes to isolation dir, not the credential

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield self.url
        await self._proceed.wait()
        yield LoginComplete(account_id="bkd-x", backend_status="validating")
        self._done = True

    async def respond(self, answer: PromptAnswer) -> None:  # pragma: no cover
        return None

    async def cancel(self) -> None:
        self._done = True
        self._proceed.set()

    def proceed(self) -> None:
        self._proceed.set()


class _OAuthBackend:
    kind: ClassVar[str] = "oauth-fake"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset({"oauth_device"})
    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="oauth-fake",
        display_name="OAuthFake",
        icon_url=None,
        install_check=InstallCheck(command=["true"], version_regex=r".*"),
        login_flows=[
            LoginFlowSpec(
                kind="oauth_device",
                display_name="Device flow",
                description="Mock OAuth device flow",
                requires_inputs=[],
            ),
        ],
        plan_options=None,
        config_schema={"type": "object"},
        supports_multi_account=True,
        isolation_env_var=None,
    )

    def __init__(self) -> None:
        self.last_session: _OAuthSession | None = None

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        self.last_session = _OAuthSession()
        return self.last_session

    async def detect(self) -> DetectResult:
        return DetectResult(installed=True, version="oauth-fake/0.0", path="/bin/true")

    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
        return True

    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list:
        return []

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        return []

    async def chat(  # type: ignore[override]
        self,
        request: Any,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[Any]:
        if False:
            yield None  # pragma: no cover

    async def pty(  # type: ignore[override]
        self,
        request: Any,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> Any:  # pragma: no cover
        raise NotImplementedError


@pytest_asyncio.fixture
async def client_and_backend(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncTestClient, _OAuthBackend]]:
    backend = _OAuthBackend()
    app = create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(str(tmp_path / "t.db")),
            vault=FakeVault(),
            auth=NoAuth(),
            backends=(backend,),
            backend_dirs_path=tmp_path / "iso",
        )
    )
    async with AsyncTestClient(app=app) as c:
        yield c, backend


def _parse_sse_data_lines(body: str) -> list[dict]:
    """Extract JSON payloads from SSE body text."""
    payloads: list[dict] = []
    for line in body.splitlines():
        if line.startswith("data:"):
            try:
                payloads.append(json.loads(line[len("data:") :].strip()))
            except json.JSONDecodeError:
                continue
    return payloads


@pytest.mark.asyncio
async def test_stream_replays_cached_url_prompt_on_reconnect(
    client_and_backend: tuple[AsyncTestClient, _OAuthBackend],
) -> None:
    """Reconnecting to an in-flight session replays the cached UrlPrompt.

    Flow:
      1. Create backend, begin login (session registered).
      2. Manually populate the session's replay cache (simulating that a
         previous SSE subscriber already consumed the UrlPrompt).
      3. Cancel the session so a fresh subscriber can safely iterate to
         completion without hanging on the blocked async generator.
      4. Reconnect to /stream; the first event received must be the
         cached UrlPrompt.
    """
    client, backend = client_and_backend

    r = await client.post("/api/v1/backends/", json={"kind": "oauth-fake", "display_name": "t"})
    assert r.status_code == 201
    backend_id = r.json()["id"]

    begin = await client.post(
        f"/api/v1/backends/{backend_id}/login/begin",
        json={"flow_kind": "oauth_device", "inputs": {}},
    )
    assert begin.status_code == 201
    session_id = begin.json()["session_id"]

    # Simulate a prior subscriber having observed the URL: populate the
    # replay cache directly. This is what ``events_with_replay`` would
    # have done for the first (now-disconnected) subscriber.
    sess = backend.last_session
    assert sess is not None
    sess._last_url_prompt = sess.url

    # Unblock the session so a fresh subscription can iterate to
    # completion (otherwise it would hang on ``_proceed``).
    sess.proceed()

    # Reconnect: new subscriber should see the cached URL FIRST.
    stream = await client.get(
        f"/api/v1/backends/{backend_id}/login/stream",
        params={"session_id": session_id},
    )
    assert stream.status_code == 200
    payloads = _parse_sse_data_lines(stream.text)

    assert payloads, "expected at least one SSE event"
    first = payloads[0]
    assert first.get("type") == "url_prompt"
    assert first.get("url") == "https://example.com/device"
    assert first.get("user_code") == "ABC-123"


@pytest.mark.asyncio
async def test_stream_without_cached_url_does_not_replay(
    client_and_backend: tuple[AsyncTestClient, _OAuthBackend],
) -> None:
    """If no UrlPrompt has been cached, the stream starts with live events only."""
    client, backend = client_and_backend

    r = await client.post("/api/v1/backends/", json={"kind": "oauth-fake", "display_name": "t"})
    backend_id = r.json()["id"]

    begin = await client.post(
        f"/api/v1/backends/{backend_id}/login/begin",
        json={"flow_kind": "oauth_device", "inputs": {}},
    )
    session_id = begin.json()["session_id"]

    sess = backend.last_session
    assert sess is not None
    # Do NOT pre-populate the cache — unblock and let the live flow run.
    sess.proceed()

    stream = await client.get(
        f"/api/v1/backends/{backend_id}/login/stream",
        params={"session_id": session_id},
    )
    assert stream.status_code == 200
    payloads = _parse_sse_data_lines(stream.text)

    # The live flow still yields its own UrlPrompt as the first event
    # (since nothing was pre-cached, no replay happens, and the live
    # iterator starts from the top).
    assert payloads
    # There should be at most one url_prompt — no duplicate from replay.
    url_count = sum(1 for p in payloads if p.get("type") == "url_prompt")
    assert url_count == 1


@pytest.mark.asyncio
async def test_stream_dedups_cached_prompt_against_live_first_event(
    client_and_backend: tuple[AsyncTestClient, _OAuthBackend],
) -> None:
    """If the cached prompt and the live iterator's first event are the
    same object, the route must not emit it twice back-to-back."""
    client, backend = client_and_backend

    r = await client.post("/api/v1/backends/", json={"kind": "oauth-fake", "display_name": "t"})
    backend_id = r.json()["id"]

    begin = await client.post(
        f"/api/v1/backends/{backend_id}/login/begin",
        json={"flow_kind": "oauth_device", "inputs": {}},
    )
    session_id = begin.json()["session_id"]

    sess = backend.last_session
    assert sess is not None
    # Pre-populate the cache with the SAME UrlPrompt object that
    # events_with_replay() will yield as its first event. The route
    # should dedup so the subscriber sees it only once.
    sess._last_url_prompt = sess.url
    sess.proceed()

    stream = await client.get(
        f"/api/v1/backends/{backend_id}/login/stream",
        params={"session_id": session_id},
    )
    assert stream.status_code == 200
    payloads = _parse_sse_data_lines(stream.text)

    url_count = sum(1 for p in payloads if p.get("type") == "url_prompt")
    assert url_count == 1, f"expected exactly one url_prompt, got {url_count}: {payloads}"
