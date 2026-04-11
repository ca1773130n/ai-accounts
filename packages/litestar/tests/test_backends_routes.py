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
    )
    app = create_app(config)
    with TestClient(app=app) as c:
        yield c


def test_list_backends_empty(client):
    response = client.get("/api/v1/backends/")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_create_backend(client):
    response = client.post(
        "/api/v1/backends/",
        json={"kind": "fake", "display_name": "Test Fake"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] == "Test Fake"
    assert body["kind"] == "fake"
    assert body["status"] == "unconfigured"
    assert body["id"].startswith("bkd-")


def test_get_backend_not_found(client):
    response = client.get("/api/v1/backends/bkd-nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "backend_not_found"


def test_create_unknown_kind(client):
    response = client.post(
        "/api/v1/backends/", json={"kind": "martian", "display_name": "x"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "backend_kind_unknown"


def test_detect_backend(client):
    created = client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "T"}
    ).json()
    response = client.post(f"/api/v1/backends/{created['id']}/detect")
    assert response.status_code == 201  # Litestar @post defaults to 201
    assert response.json()["installed"] is True


def test_login_validate_happy_path(client):
    created = client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "T"}
    ).json()
    login = client.post(
        f"/api/v1/backends/{created['id']}/login",
        json={"flow_kind": "api_key", "inputs": {"api_key": "x"}},
    )
    assert login.status_code == 201
    validate = client.post(f"/api/v1/backends/{created['id']}/validate")
    assert validate.status_code == 201
    assert validate.json()["status"] == "ready"


def test_delete_backend(client):
    created = client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "T"}
    ).json()
    response = client.delete(f"/api/v1/backends/{created['id']}")
    assert response.status_code == 204
    get_response = client.get(f"/api/v1/backends/{created['id']}")
    assert get_response.status_code == 404


def test_list_after_create(client):
    client.post("/api/v1/backends/", json={"kind": "fake", "display_name": "A"})
    client.post("/api/v1/backends/", json={"kind": "fake", "display_name": "B"})
    response = client.get("/api/v1/backends/")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
