from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.services.accounts import AccountService
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


def _get_account_service(client: AsyncTestClient) -> AccountService:
    """Retrieve the AccountService that the app uses via its DI provider."""
    provide = client.app.dependencies["account_service"]  # type: ignore[union-attr]
    return provide.dependency()


async def _create_backend(client: AsyncTestClient) -> str:
    r = await client.post("/api/v1/backends/", json={"kind": "fake", "display_name": "T"})
    assert r.status_code == 201
    return r.json()["id"]


async def _create_backend_with_credential(client: AsyncTestClient) -> str:
    """Create a backend, store a credential, and validate it so chat works."""
    backend_id = await _create_backend(client)
    account_service = _get_account_service(client)
    await account_service.store_credential(backend_id, b"sk-fake-test")
    await account_service.validate(backend_id)
    return backend_id


@pytest.mark.asyncio
async def test_create_and_list_sessions(client: AsyncTestClient) -> None:
    backend_id = await _create_backend(client)

    r = await client.post(
        "/api/v1/conversations/",
        json={"backend_id": backend_id, "model": "fake-1"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["backend_id"] == backend_id
    assert body["model"] == "fake-1"
    assert body["id"].startswith("cht-")

    r = await client.get(f"/api/v1/conversations/?backend_id={backend_id}")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


@pytest.mark.asyncio
async def test_list_sessions_empty(client: AsyncTestClient) -> None:
    r = await client.get("/api/v1/conversations/")
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_get_session(client: AsyncTestClient) -> None:
    backend_id = await _create_backend(client)

    r = await client.post(
        "/api/v1/conversations/",
        json={"backend_id": backend_id, "model": "fake-1"},
    )
    session_id = r.json()["id"]

    r = await client.get(f"/api/v1/conversations/{session_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == session_id
    assert body["messages"] == []


@pytest.mark.asyncio
async def test_send_message_sse(client: AsyncTestClient) -> None:
    backend_id = await _create_backend_with_credential(client)

    r = await client.post(
        "/api/v1/conversations/",
        json={"backend_id": backend_id, "model": "fake-1"},
    )
    session_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/conversations/{session_id}/messages",
        json={"content": "Hello"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
