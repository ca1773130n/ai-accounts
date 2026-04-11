from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from litestar.testing import AsyncTestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.backends.codex import CodexBackend
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
            backends=(FakeBackend(), ClaudeBackend(), CodexBackend()),
            backend_dirs_path=tmp_path / "iso",
        )
    )
    async with AsyncTestClient(app=app) as c:
        yield c


@pytest.mark.asyncio
async def test_meta_returns_all_registered_backends(client: AsyncTestClient):
    r = await client.get("/api/v1/backends/_meta")
    assert r.status_code == 200
    body = r.json()
    kinds = [m["kind"] for m in body["items"]]
    assert set(kinds) == {"fake", "claude", "codex"}


@pytest.mark.asyncio
async def test_meta_claude_has_cli_browser_flow(client: AsyncTestClient):
    r = await client.get("/api/v1/backends/_meta")
    claude = next(m for m in r.json()["items"] if m["kind"] == "claude")
    flow_kinds = [f["kind"] for f in claude["login_flows"]]
    assert "cli_browser" in flow_kinds
    assert claude["isolation_env_var"] == "CLAUDE_CONFIG_DIR"
