from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from litestar.testing import AsyncTestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
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


@pytest.mark.asyncio
async def test_begin_returns_session_id(client: AsyncTestClient):
    r = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "t"}
    )
    backend_id = r.json()["id"]

    begin = await client.post(
        f"/api/v1/backends/{backend_id}/login/begin",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    assert begin.status_code == 201
    assert begin.json()["session_id"].startswith("sess-")


@pytest.mark.asyncio
async def test_begin_unknown_backend_returns_404(client: AsyncTestClient):
    begin = await client.post(
        "/api/v1/backends/bkd-nope/login/begin",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    assert begin.status_code == 404


@pytest.mark.asyncio
async def test_begin_unsupported_flow_returns_400(client: AsyncTestClient):
    r = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "t"}
    )
    backend_id = r.json()["id"]
    begin = await client.post(
        f"/api/v1/backends/{backend_id}/login/begin",
        json={"flow_kind": "martian_flow", "inputs": {}},
    )
    assert begin.status_code == 400


@pytest.mark.asyncio
async def test_respond_unknown_session_returns_404(client: AsyncTestClient):
    r = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "t"}
    )
    backend_id = r.json()["id"]
    resp = await client.post(
        f"/api/v1/backends/{backend_id}/login/respond",
        json={"session_id": "sess-nope", "prompt_id": "key", "answer": "x"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_unknown_session_is_idempotent(client: AsyncTestClient):
    r = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "t"}
    )
    backend_id = r.json()["id"]
    cancel = await client.post(
        f"/api/v1/backends/{backend_id}/login/cancel",
        json={"session_id": "sess-nope"},
    )
    assert cancel.status_code == 204


@pytest.mark.asyncio
async def test_begin_then_respond_drives_session(client: AsyncTestClient):
    """Smoke test: /begin registers a session, /respond reaches it.

    Full SSE stream verification is covered by the core test for
    LoginSessionRegistry + FakeLoginSession. Here we verify the routes
    correctly reach the session via the registry without needing to
    consume the SSE stream (which is finicky under AsyncTestClient).
    """
    r = await client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "t"}
    )
    backend_id = r.json()["id"]

    begin = await client.post(
        f"/api/v1/backends/{backend_id}/login/begin",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    assert begin.status_code == 201
    session_id = begin.json()["session_id"]

    # respond reaches the session via the registry
    resp = await client.post(
        f"/api/v1/backends/{backend_id}/login/respond",
        json={"session_id": session_id, "prompt_id": "key", "answer": "sk-fake-x"},
    )
    assert resp.status_code == 204

    # cancel cleans up
    cancel = await client.post(
        f"/api/v1/backends/{backend_id}/login/cancel",
        json={"session_id": session_id},
    )
    assert cancel.status_code == 204
