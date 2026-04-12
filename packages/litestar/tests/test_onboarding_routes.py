import pytest
from litestar.testing import TestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
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


def test_start_onboarding(client):
    response = client.post("/api/v1/onboarding/")
    assert response.status_code == 201
    body = response.json()
    assert body["current_step"] == "welcome"
    assert body["id"].startswith("onb-")


def test_get_unknown_onboarding_returns_404(client):
    response = client.get("/api/v1/onboarding/onb-nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "onboarding_not_found"


def test_begin_login_returns_session_id(client):
    started = client.post("/api/v1/onboarding/").json()
    onb_id = started["id"]

    detect = client.post(f"/api/v1/onboarding/{onb_id}/detect")
    assert detect.status_code == 201

    pick = client.post(
        f"/api/v1/onboarding/{onb_id}/pick",
        json={"kind": "fake", "display_name": "Test"},
    )
    assert pick.status_code == 201
    assert pick.json()["kind"] == "fake"

    login = client.post(
        f"/api/v1/onboarding/{onb_id}/login",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    assert login.status_code == 201
    body = login.json()
    assert "session_id" in body
    assert body["session_id"].startswith("sess-")
