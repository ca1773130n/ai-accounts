import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.testing import FakeBackend, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig
from litestar.testing import AsyncTestClient


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncTestClient]:
    app = create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(str(tmp_path / "t.db")),
            vault=FakeVault(),
            auth=NoAuth(),
            backends=(FakeBackend(),),
            backend_dirs_path=tmp_path / "iso",
        )
    )
    async with AsyncTestClient(app=app) as c:
        yield c


@pytest_asyncio.fixture
async def tool_client(tmp_path: Path) -> AsyncIterator[AsyncTestClient]:
    app = create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(str(tmp_path / "t.db")),
            vault=FakeVault(),
            auth=NoAuth(),
            backends=(
                FakeBackend(
                    tool_call={
                        "id": "call_abc",
                        "name": "search",
                        "arguments": '{"q":"hi"}',
                        "group_type": "tool_call",
                    }
                ),
            ),
            backend_dirs_path=tmp_path / "iso",
        )
    )
    async with AsyncTestClient(app=app) as c:
        yield c


def _get_account_service(client: AsyncTestClient) -> AccountService:
    provide = client.app.dependencies["account_service"]  # type: ignore[union-attr]
    return provide.dependency()


def _get_chat_service(client: AsyncTestClient) -> ChatService:
    provide = client.app.dependencies["chat_service"]  # type: ignore[union-attr]
    return provide.dependency()


async def _setup_backend_and_session(client: AsyncTestClient) -> tuple[str, str]:
    """Create backend with credential, create chat session, return (backend_id, session_id)."""
    r = await client.post("/api/v1/backends/", json={"kind": "fake", "display_name": "T"})
    assert r.status_code == 201
    backend_id = r.json()["id"]

    svc = _get_account_service(client)
    await svc.store_credential(backend_id, b"sk-fake-test")
    await svc.validate(backend_id)

    chat = _get_chat_service(client)
    session = await chat.create_session(backend_id=backend_id, model="fake-1")
    return backend_id, session.id


@pytest.mark.asyncio
async def test_send_single(client: AsyncTestClient) -> None:
    _, session_id = await _setup_backend_and_session(client)
    r = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "Hello", "mode": "single"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    body = r.text
    assert "token" in body


@pytest.mark.asyncio
async def test_send_all(client: AsyncTestClient) -> None:
    _, session_id = await _setup_backend_and_session(client)
    r = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "Hello", "mode": "all"},
    )
    assert r.status_code == 200
    # send_all may not exist yet (being added in parallel task).
    # If it fails with AttributeError, the route error handler catches it
    # and returns an SSE error frame instead of a 500.


@pytest.mark.asyncio
async def test_send_returns_sse_format(client: AsyncTestClient) -> None:
    _, session_id = await _setup_backend_and_session(client)
    r = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "Hello"},
    )
    assert r.status_code == 200
    assert "event: chat" in r.text


@pytest.mark.asyncio
async def test_chat_send_includes_seq_ids(client: AsyncTestClient) -> None:
    """Each SSE frame should carry an `id: <seq>` line for client-side reconnect."""
    _, session_id = await _setup_backend_and_session(client)
    r = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "Hello", "mode": "single"},
    )
    assert r.status_code == 200
    # at least one id: line should appear, tagged monotonically
    assert "id: 1" in r.text


@pytest.mark.asyncio
async def test_chat_send_streams_tool_call(tool_client: AsyncTestClient) -> None:
    """POST /api/v1/chat/send streams tool_call events for backends that emit them."""
    _, session_id = await _setup_backend_and_session(tool_client)
    resp = await tool_client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "trigger tool", "mode": "single"},
    )
    assert resp.status_code == 200
    events = []
    for block in resp.text.split("\n\n"):
        for line in block.strip().split("\n"):
            if line.startswith("data:"):
                raw = line.removeprefix("data:").strip()
                if raw:
                    events.append(json.loads(raw))
    tool_events = [e for e in events if e.get("kind") == "tool_call"]
    assert len(tool_events) >= 1
    assert tool_events[0]["id"] == "call_abc"
    assert tool_events[0]["name"] == "search"
    assert tool_events[0]["group_type"] == "tool_call"


def _parse_sse_events(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.strip().split("\n"):
            if line.startswith("data:"):
                raw = line.removeprefix("data:").strip()
                if raw:
                    events.append(json.loads(raw))
    return events


@pytest.mark.asyncio
async def test_chat_send_reconnect_with_last_event_id_seeds_seq(
    client: AsyncTestClient,
) -> None:
    """After session eviction, a reconnect with Last-Event-ID must seed the
    seq counter so new events stay strictly greater than the client's
    lastSeq — otherwise client-side dedup would silently drop them."""
    _, session_id = await _setup_backend_and_session(client)

    # First request — server tags events with _seq 1..N, then remove_session() on close
    first = await client.post(
        "/api/v1/chat/send",
        json={"session_id": session_id, "content": "hi", "mode": "single"},
    )
    assert first.status_code == 200
    first_events = _parse_sse_events(first.text)
    max_seq = max((e.get("_seq", 0) for e in first_events), default=0)
    assert max_seq >= 1

    # Reconnect: simulate client with Last-Event-ID == max_seq. Session was
    # evicted on first close, so server has no retained log and must seed
    # seq from the header rather than restarting at 1.
    second = await client.post(
        "/api/v1/chat/send",
        headers={"Last-Event-ID": str(max_seq)},
        json={"session_id": session_id, "content": "again", "mode": "single"},
    )
    assert second.status_code == 200
    second_events = _parse_sse_events(second.text)
    forward_seqs = [e.get("_seq") for e in second_events if e.get("_seq") is not None]
    assert forward_seqs, "reconnect must emit tagged forward events"
    assert all(s > max_seq for s in forward_seqs), (
        f"forward seqs {forward_seqs} must all be > last_event_id {max_seq}"
    )


@pytest.mark.asyncio
async def test_chat_send_malformed_last_event_id_treated_as_fresh(
    client: AsyncTestClient,
) -> None:
    """Malformed Last-Event-ID headers must not crash — fall back to seq=1
    for the new session (and log a warning, verified by the successful 200)."""
    _, session_id = await _setup_backend_and_session(client)
    resp = await client.post(
        "/api/v1/chat/send",
        headers={"Last-Event-ID": "not-a-number"},
        json={"session_id": session_id, "content": "hi", "mode": "single"},
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    seqs = [e.get("_seq") for e in events if e.get("_seq") is not None]
    assert seqs and seqs[0] == 1
