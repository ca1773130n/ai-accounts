"""Smoke + happy-path tests for the discovery route."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from litestar.testing import TestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.services.discovery import DiscoveredConfig
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


def test_discovery_list_returns_items(client):
    """GET /discovery/ delegates to AccountService.discover_existing."""
    stub = [
        DiscoveredConfig(
            kind="claude",
            path="/home/u/.claude-work",
            suggested_name="work",
            is_logged_in=True,
            error=None,
        ),
        DiscoveredConfig(
            kind="codex",
            path="/home/u/.codex_old",
            suggested_name="codex_old",
            is_logged_in=False,
            error="Not logged in",
        ),
    ]
    with patch(
        "ai_accounts_core.services.accounts.AccountService.discover_existing",
        new=AsyncMock(return_value=stub),
    ):
        r = client.get("/api/v1/discovery/")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    ready = next(i for i in body["items"] if i["is_logged_in"])
    assert ready["kind"] == "claude"
    assert ready["suggested_name"] == "work"
    not_ready = next(i for i in body["items"] if not i["is_logged_in"])
    assert not_ready["error"] == "Not logged in"


def test_discovery_list_empty(client):
    with patch(
        "ai_accounts_core.services.accounts.AccountService.discover_existing",
        new=AsyncMock(return_value=[]),
    ):
        body = client.get("/api/v1/discovery/").json()
    assert body == {"items": []}


def test_discovery_import_creates_backend(client, tmp_path):
    """POST /discovery/import calls import_discovered and returns the BackendDTO."""
    # Use a real path so config_path validation passes (it checks dir exists).
    cfg_dir = tmp_path / ".fake-personal"
    cfg_dir.mkdir()
    r = client.post(
        "/api/v1/discovery/import",
        json={"kind": "fake", "path": str(cfg_dir), "display_name": "personal"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "fake"
    assert body["display_name"] == "personal"
    assert body["config"]["config_path"] == str(cfg_dir)
