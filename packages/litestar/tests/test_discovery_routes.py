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
        # Already-imported, still healthy — backend_id surfaces so the UI
        # can hide its Import button and surface a "re-verified" badge.
        DiscoveredConfig(
            kind="claude",
            path="/home/u/.claude-personal",
            suggested_name="personal",
            is_logged_in=True,
            error=None,
            backend_id="bkd-abc123",
        ),
    ]
    with patch(
        "ai_accounts_core.services.accounts.AccountService.discover_existing",
        new=AsyncMock(return_value=stub),
    ):
        r = client.get("/api/v1/discovery/")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    new_ready = next(i for i in body["items"] if i["is_logged_in"] and not i["backend_id"])
    assert new_ready["kind"] == "claude"
    assert new_ready["suggested_name"] == "work"
    not_ready = next(i for i in body["items"] if not i["is_logged_in"])
    assert not_ready["error"] == "Not logged in"
    imported = next(i for i in body["items"] if i["backend_id"])
    assert imported["backend_id"] == "bkd-abc123"
    assert imported["is_logged_in"] is True


def test_discovery_list_empty(client):
    with patch(
        "ai_accounts_core.services.accounts.AccountService.discover_existing",
        new=AsyncMock(return_value=[]),
    ):
        body = client.get("/api/v1/discovery/").json()
    assert body == {"items": []}


def test_discovery_import_creates_backend(client):
    """POST /discovery/import calls AccountService.import_discovered with the
    submitted fields and returns the resulting BackendDTO.

    We mock import_discovered to sidestep AccountService.create's config_path
    validation (which requires the path to live under $HOME or the isolation
    base dir — tmp_path satisfies neither in test_session scope). The
    contract under test is the route's wiring, not the service.
    """
    from ai_accounts_core.domain.backend import Backend, BackendStatus
    from datetime import datetime, timezone

    stub_backend = Backend(
        id="bkd-newimport",
        kind="fake",
        display_name="personal",
        config={"config_path": "/home/u/.fake-personal"},
        status=BackendStatus.READY,
        created_at=datetime.now(timezone.utc),
    )
    with patch(
        "ai_accounts_core.services.accounts.AccountService.import_discovered",
        new=AsyncMock(return_value=stub_backend),
    ) as mock_import:
        r = client.post(
            "/api/v1/discovery/import",
            json={"kind": "fake", "path": "/home/u/.fake-personal", "display_name": "personal"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "bkd-newimport"
    assert body["kind"] == "fake"
    assert body["display_name"] == "personal"
    mock_import.assert_awaited_once_with(
        "fake", "/home/u/.fake-personal", display_name="personal"
    )
