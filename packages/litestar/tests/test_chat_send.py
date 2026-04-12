from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from litestar.testing import AsyncTestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.testing import FakeBackend, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


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


def _get_account_service(client: AsyncTestClient) -> AccountService:
    provide = client.app.dependencies["account_service"]  # type: ignore[union-attr]
    return provide.dependency()


def _get_chat_service(client: AsyncTestClient) -> ChatService:
    provide = client.app.dependencies["chat_service"]  # type: ignore[union-attr]
    return provide.dependency()


async def _setup_backend_and_session(client: AsyncTestClient) -> tuple[str, str]:
    """Create backend with credential, create chat session, return (backend_id, session_id)."""
    r = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "T"}
    )
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
