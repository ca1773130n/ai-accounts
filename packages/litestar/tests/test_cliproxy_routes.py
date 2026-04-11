from unittest.mock import AsyncMock, patch

import pytest
from litestar.testing import TestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.cliproxy import CliproxyInstallResult, CliproxyLoginInfo
from ai_accounts_core.testing import FakeBackend, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


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


def test_cliproxy_status_returns_bool(client):
    r = client.get("/api/v1/cliproxy/status")
    assert r.status_code == 200
    body = r.json()
    assert "installed" in body
    assert isinstance(body["installed"], bool)


def test_cliproxy_install_mocked(client):
    fake = CliproxyInstallResult(
        success=True,
        display="go install github.com/.../server@latest",
        stdout="",
        stderr="",
        binary_path="/usr/local/bin/cliproxyapi",
    )
    with patch(
        "ai_accounts_litestar.routes.cliproxy.install_cliproxy",
        new=AsyncMock(return_value=fake),
    ):
        r = client.post("/api/v1/cliproxy/install")
    assert r.status_code == 201
    body = r.json()
    assert body["success"] is True


def test_cliproxy_login_begin_imported(client):
    fake_info = CliproxyLoginInfo(imported=True, output="imported credentials")
    with patch(
        "ai_accounts_litestar.routes.cliproxy.start_cliproxy_login",
        new=AsyncMock(return_value=(None, fake_info)),
    ):
        r = client.post(
            "/api/v1/cliproxy/login/begin",
            json={"backend_kind": "gemini"},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "imported"


def test_cliproxy_login_begin_started(client):
    fake_info = CliproxyLoginInfo(
        oauth_url="https://oauth.example.test/auth?code=xyz",
        device_code="ABCD-1234",
    )
    with patch(
        "ai_accounts_litestar.routes.cliproxy.start_cliproxy_login",
        new=AsyncMock(return_value=(None, fake_info)),
    ):
        r = client.post(
            "/api/v1/cliproxy/login/begin",
            json={"backend_kind": "claude"},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "started"
    assert body["oauth_url"] == "https://oauth.example.test/auth?code=xyz"
    assert body["device_code"] == "ABCD-1234"


def test_cliproxy_callback_forward_rejects_missing_code(client):
    r = client.post(
        "/api/v1/cliproxy/login/callback-forward",
        json={"callback_url": "https://example.test/cb?state=abc"},
    )
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["status"] == "error"
