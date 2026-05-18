"""Tests for the AuthMiddleware that actually enforces config.auth."""

from __future__ import annotations

from ai_accounts_core.adapters.auth_apikey import ApiKeyAuth
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.testing import FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig
from litestar.testing import TestClient


def _make_client(tmp_path, auth) -> TestClient:
    config = AiAccountsConfig(
        env="development",
        storage=SqliteStorage(str(tmp_path / "auth.db")),
        vault=FakeVault(),
        auth=auth,
    )
    return TestClient(app=create_app(config))


def test_apikey_auth_rejects_request_without_bearer(tmp_path):
    with _make_client(tmp_path, ApiKeyAuth(token="s3cret")) as client:
        r = client.get("/api/v1/backends/")
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "unauthorized"


def test_apikey_auth_rejects_wrong_token(tmp_path):
    with _make_client(tmp_path, ApiKeyAuth(token="s3cret")) as client:
        r = client.get(
            "/api/v1/backends/",
            headers={"authorization": "Bearer nope"},
        )
        assert r.status_code == 401


def test_apikey_auth_accepts_valid_bearer(tmp_path):
    with _make_client(tmp_path, ApiKeyAuth(token="s3cret")) as client:
        r = client.get(
            "/api/v1/backends/",
            headers={"authorization": "Bearer s3cret"},
        )
        # 200 on the listing (empty) — proves we got past auth.
        assert r.status_code == 200


def test_health_endpoint_bypasses_auth(tmp_path):
    """/health must stay reachable without credentials for liveness probes."""
    with _make_client(tmp_path, ApiKeyAuth(token="s3cret")) as client:
        r = client.get("/health")
        assert r.status_code == 200


def test_noauth_accepts_every_request(tmp_path):
    with _make_client(tmp_path, NoAuth()) as client:
        r = client.get("/api/v1/backends/")
        assert r.status_code == 200


def test_no_auth_configured_skips_middleware(tmp_path):
    """In development, auth=None is allowed and skips the middleware entirely
    (production guard refuses auth=None, so this path is dev-only)."""
    with _make_client(tmp_path, auth=None) as client:
        r = client.get("/api/v1/backends/")
        assert r.status_code == 200
