from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.install import InstallResult
from ai_accounts_core.testing import FakeBackend, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig
from litestar.testing import TestClient


@pytest.fixture
def client(tmp_path):
    config = AiAccountsConfig(
        env="development",
        storage=SqliteStorage(str(tmp_path / "test.db")),
        vault=FakeVault(),
        auth=NoAuth(),
        backends=(FakeBackend(),),
        backend_dirs_path=tmp_path / "backend_dirs",
    )
    app = create_app(config)
    with TestClient(app=app) as c:
        yield c


def test_install_unknown_kind_returns_400(client):
    r = client.post("/api/v1/backends/martian/install")
    assert r.status_code == 400


def test_install_claude_mocked_success(client):
    fake = InstallResult(
        kind="claude",
        success=True,
        display="npm install -g @anthropic-ai/claude-code",
        stdout="added 1 package",
        stderr="",
        exit_code=0,
        binary_path="/usr/local/bin/claude",
    )
    with patch(
        "ai_accounts_litestar.routes.install.install_backend_cli",
        new=AsyncMock(return_value=fake),
    ):
        r = client.post("/api/v1/backends/claude/install")
    assert r.status_code == 201
    body = r.json()
    assert body["success"] is True
    assert body["kind"] == "claude"
