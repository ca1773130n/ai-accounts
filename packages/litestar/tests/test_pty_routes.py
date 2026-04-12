import pytest
from litestar.testing import AsyncTestClient

from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.testing.fakes import FakeBackend, FakeStorage, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest.fixture
async def client(tmp_path):
    config = AiAccountsConfig(
        storage=FakeStorage(),
        vault=FakeVault(),
        backends=(FakeBackend(),),
        backend_dirs_path=tmp_path,
    )
    app = create_app(config)
    async with AsyncTestClient(app) as tc:
        yield tc


def _get_account_service(client: AsyncTestClient) -> AccountService:
    provide = client.app.dependencies["account_service"]  # type: ignore[union-attr]
    return provide.dependency()


async def _create_ready_backend(client: AsyncTestClient) -> str:
    r = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "T"}
    )
    assert r.status_code == 201
    backend_id = r.json()["id"]
    svc = _get_account_service(client)
    await svc.store_credential(backend_id, b"sk-fake-test")
    await svc.validate(backend_id)
    return backend_id


@pytest.mark.asyncio
async def test_pty_spawn(client):
    backend_id = await _create_ready_backend(client)
    r = await client.post(
        "/api/v1/pty/spawn",
        json={
            "backend_id": backend_id,
            "command": ["/bin/echo", "hi"],
            "cols": 80,
            "rows": 24,
        },
    )
    assert r.status_code == 201
    assert "session_id" in r.json()


@pytest.mark.asyncio
async def test_pty_kill(client):
    backend_id = await _create_ready_backend(client)
    r = await client.post(
        "/api/v1/pty/spawn",
        json={
            "backend_id": backend_id,
            "command": ["/bin/sh"],
            "cols": 80,
            "rows": 24,
        },
    )
    session_id = r.json()["session_id"]
    r = await client.post(f"/api/v1/pty/{session_id}/kill")
    assert r.status_code == 200
