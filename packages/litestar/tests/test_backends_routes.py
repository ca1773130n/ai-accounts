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


def test_login_api_key_returns_complete(client):
    created = client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "T"}
    ).json()
    login = client.post(
        f"/api/v1/backends/{created['id']}/login",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    assert login.status_code == 201
    body = login.json()
    assert body["kind"] == "complete"
    assert body["backend"]["status"] == "validating"
    assert body["oauth"] is None

    validate = client.post(f"/api/v1/backends/{created['id']}/validate")
    assert validate.status_code == 201
    assert validate.json()["status"] == "ready"


def test_login_oauth_returns_pending_with_challenge(client):
    created = client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "T"}
    ).json()
    login = client.post(
        f"/api/v1/backends/{created['id']}/login",
        json={"flow_kind": "oauth_device", "inputs": {}},
    )
    assert login.status_code == 201
    body = login.json()
    assert body["kind"] == "pending"
    assert body["oauth"]["user_code"] == "FAKE-1234"
    assert body["oauth"]["handle"].startswith("fake-handle-")
    assert body["backend"] is None


def test_poll_login_eventually_completes(client):
    created = client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "T"}
    ).json()
    start = client.post(
        f"/api/v1/backends/{created['id']}/login",
        json={"flow_kind": "oauth_device", "inputs": {}},
    ).json()
    handle = start["oauth"]["handle"]

    first = client.post(
        f"/api/v1/backends/{created['id']}/login/poll",
        json={"handle": handle},
    )
    assert first.status_code == 201
    assert first.json()["kind"] == "pending"

    second = client.post(
        f"/api/v1/backends/{created['id']}/login/poll",
        json={"handle": handle},
    )
    assert second.status_code == 201
    assert second.json()["kind"] == "complete"
    assert second.json()["backend"]["status"] == "validating"


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


def test_patch_backend_display_name(client):
    created = client.post(
        "/api/v1/backends/", json={"kind": "fake", "display_name": "Old"}
    ).json()
    response = client.patch(
        f"/api/v1/backends/{created['id']}",
        json={"display_name": "New"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "New"
    assert body["id"] == created["id"]

    refetched = client.get(f"/api/v1/backends/{created['id']}")
    assert refetched.json()["display_name"] == "New"


def test_patch_backend_config(client):
    created = client.post(
        "/api/v1/backends/",
        json={"kind": "fake", "display_name": "X", "config": {"plan": "free"}},
    ).json()
    response = client.patch(
        f"/api/v1/backends/{created['id']}",
        json={"config": {"plan": "pro", "email": "a@b.c"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["config"] == {"plan": "pro", "email": "a@b.c"}
    assert body["display_name"] == "X"  # unchanged


def test_patch_backend_not_found(client):
    response = client.patch(
        "/api/v1/backends/bkd-nope",
        json={"display_name": "x"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "backend_not_found"
