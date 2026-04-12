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
async def test_pick_returns_account(client):
    b1 = await _create_ready_backend(client)
    r = await client.post("/api/v1/scheduler/pick", json={})
    assert r.status_code == 200
    assert r.json()["backend_id"] == b1


@pytest.mark.asyncio
async def test_pick_with_kind(client):
    await _create_ready_backend(client)
    r = await client.post("/api/v1/scheduler/pick", json={"kind": "fake"})
    assert r.status_code == 200
    assert r.json()["kind"] == "fake"


@pytest.mark.asyncio
async def test_pick_no_accounts(client):
    r = await client.post("/api/v1/scheduler/pick", json={})
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_chain_crud(client):
    b1 = await _create_ready_backend(client)
    b2 = await _create_ready_backend(client)

    r = await client.put(
        "/api/v1/scheduler/chain",
        json={
            "entries": [
                {"backend_id": b2, "priority": 0},
                {"backend_id": b1, "priority": 1},
            ]
        },
    )
    assert r.status_code == 200

    r = await client.get("/api/v1/scheduler/chain")
    assert r.status_code == 200
    assert r.json()["entries"][0]["backend_id"] == b2


@pytest.mark.asyncio
async def test_health(client):
    await _create_ready_backend(client)
    r = await client.get("/api/v1/scheduler/health")
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 1


@pytest.mark.asyncio
async def test_health_single(client):
    b1 = await _create_ready_backend(client)
    r = await client.get(f"/api/v1/scheduler/health/{b1}")
    assert r.status_code == 200
    body = r.json()
    assert body["backend_id"] == b1
    assert body["kind"] == "fake"


@pytest.mark.asyncio
async def test_mark_limited(client):
    b1 = await _create_ready_backend(client)
    r = await client.post(
        "/api/v1/scheduler/mark-limited",
        json={"backend_id": b1, "cooldown_seconds": 3600, "reason": "test"},
    )
    assert r.status_code == 204
    # Should skip rate-limited account — returns 204
    r = await client.post("/api/v1/scheduler/pick", json={})
    assert r.status_code == 204
