import json
import subprocess
from unittest.mock import patch

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend


def _no_keychain():
    """Force the macOS keychain probe to report 'not found' (rc=1).

    Tests assert the file-probe fallback. On a developer's macOS where a real
    Claude credential lives in the keychain, the probe would short-circuit to
    True and mask the file probe — these tests would then pass for the wrong
    reason, or fail when the dev account differs from the assumption.
    """
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"")
    return patch("ai_accounts_core.backends.claude.subprocess.run", return_value=fake)


@pytest.mark.asyncio
async def test_validate_returns_false_when_isolation_dir_empty(tmp_path):
    backend = ClaudeBackend()
    with _no_keychain():
        ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_validate_returns_true_when_credentials_present(tmp_path):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({"oauth_token": "sk-ant-..."}))
    backend = ClaudeBackend()
    with _no_keychain():
        ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is True


@pytest.mark.asyncio
async def test_validate_returns_false_when_credentials_corrupt(tmp_path):
    creds = tmp_path / ".credentials.json"
    creds.write_text("not valid json{{{")
    backend = ClaudeBackend()
    with _no_keychain():
        ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_validate_returns_true_when_macos_keychain_has_entry(tmp_path):
    """On macOS, a populated keychain entry alone is enough (CLI default storage)."""
    fake_ok = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    backend = ClaudeBackend()
    with patch("ai_accounts_core.backends.claude.sys.platform", "darwin"), patch(
        "ai_accounts_core.backends.claude.subprocess.run", return_value=fake_ok
    ):
        ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is True


@pytest.mark.asyncio
async def test_list_models_returns_known_set(tmp_path):
    """Static fallback when cliproxy isn't reachable. Force the live path
    to 'unavailable' so the test machine's real cliproxyapi (if any)
    doesn't shadow the static set."""
    from unittest.mock import AsyncMock as _AsyncMock
    backend = ClaudeBackend()
    with patch(
        "ai_accounts_core.cliproxy.cliproxy_list_models",
        new=_AsyncMock(return_value=None),
    ):
        models = await backend.list_models(b"", isolation_dir=tmp_path)
    ids = {m.id for m in models}
    assert "claude-sonnet-4-6" in ids
    assert all(m.context_window for m in models)
