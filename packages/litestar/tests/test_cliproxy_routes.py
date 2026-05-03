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


# ── /login/status — completion polling for the device-code flow ──

def test_login_status_unknown_session(client):
    r = client.get("/api/v1/cliproxy/login/status?session_id=does-not-exist")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "unknown"
    assert body["message"] == "No such session"


def test_login_status_running_then_completed(client):
    """Drive the in-process registry directly and verify the route surfaces it."""
    from ai_accounts_litestar.routes.cliproxy import _record_login_state, _LOGIN_STATE

    sid = "test-session-running"
    try:
        _record_login_state(sid, "running", "Awaiting OAuth completion", None)
        r = client.get(f"/api/v1/cliproxy/login/status?session_id={sid}")
        assert r.status_code == 200
        assert r.json() == {
            "state": "running",
            "message": "Awaiting OAuth completion",
            "returncode": None,
        }
        # Now flip it to completed (simulating _reap finishing).
        _record_login_state(sid, "completed", "API proxy login completed", 0)
        r = client.get(f"/api/v1/cliproxy/login/status?session_id={sid}")
        assert r.json() == {
            "state": "completed",
            "message": "API proxy login completed",
            "returncode": 0,
        }
    finally:
        _LOGIN_STATE.pop(sid, None)


def test_login_status_failed_carries_returncode(client):
    from ai_accounts_litestar.routes.cliproxy import _record_login_state, _LOGIN_STATE

    sid = "test-session-failed"
    try:
        _record_login_state(sid, "failed", "cliproxyapi exited with code 1", 1)
        body = client.get(
            f"/api/v1/cliproxy/login/status?session_id={sid}"
        ).json()
        assert body == {
            "state": "failed",
            "message": "cliproxyapi exited with code 1",
            "returncode": 1,
        }
    finally:
        _LOGIN_STATE.pop(sid, None)


def test_login_status_timeout(client):
    from ai_accounts_litestar.routes.cliproxy import _record_login_state, _LOGIN_STATE

    sid = "test-session-timeout"
    try:
        _record_login_state(sid, "timeout", "Login timed out after 5 minutes", None)
        body = client.get(
            f"/api/v1/cliproxy/login/status?session_id={sid}"
        ).json()
        assert body["state"] == "timeout"
        assert "5 minutes" in body["message"]
    finally:
        _LOGIN_STATE.pop(sid, None)


def test_login_state_lru_evicts_oldest():
    """The bounded LRU keeps memory in check across long-lived processes."""
    from ai_accounts_litestar.routes.cliproxy import (
        _LOGIN_STATE,
        _LOGIN_STATE_MAX,
        _record_login_state,
    )

    _LOGIN_STATE.clear()
    try:
        # Fill to the cap.
        for i in range(_LOGIN_STATE_MAX):
            _record_login_state(f"sess-{i}", "completed", "ok", 0)
        assert len(_LOGIN_STATE) == _LOGIN_STATE_MAX
        # One more push should evict the oldest (insertion order in dict ≥ 3.7).
        _record_login_state("sess-overflow", "completed", "ok", 0)
        assert len(_LOGIN_STATE) == _LOGIN_STATE_MAX
        assert "sess-0" not in _LOGIN_STATE  # oldest evicted
        assert "sess-overflow" in _LOGIN_STATE
    finally:
        _LOGIN_STATE.clear()


def test_login_begin_started_returns_session_id(client):
    """The new session_id field is populated when a real subprocess is spawned."""
    import asyncio

    fake_info = CliproxyLoginInfo(
        oauth_url="https://oauth.example.test/device",
        device_code="WXYZ-7890",
    )
    # proc must be non-None for session_id to be issued; use a stub with the
    # bare interface the _reap closure needs (wait, kill, returncode, stdout).
    class _FakeProc:
        returncode = 0
        stdout = None  # _reap handles None

        async def wait(self):
            return 0

        def kill(self):
            pass

    with patch(
        "ai_accounts_litestar.routes.cliproxy.start_cliproxy_login",
        new=AsyncMock(return_value=(_FakeProc(), fake_info)),
    ):
        body = client.post(
            "/api/v1/cliproxy/login/begin",
            json={"backend_kind": "claude"},
        ).json()
    assert body["status"] == "started"
    assert body["session_id"] is not None
    assert len(body["session_id"]) == 32  # uuid4 hex
