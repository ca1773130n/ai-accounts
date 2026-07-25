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


def _claude_on_path():
    """Pretend the `claude` CLI is installed.

    validate() short-circuits to False when ``shutil.which("claude")`` is None,
    so without this the CLI's absence (e.g. in CI) masks the credential logic
    these tests exercise — the True cases fail and the False cases pass for the
    wrong reason.
    """
    return patch("ai_accounts_core.backends.claude.shutil.which", return_value="/usr/bin/claude")


@pytest.mark.asyncio
async def test_validate_returns_false_when_isolation_dir_empty(tmp_path):
    backend = ClaudeBackend()
    with _no_keychain(), _claude_on_path():
        ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_validate_returns_true_when_credentials_present(tmp_path):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({"oauth_token": "sk-ant-..."}))
    backend = ClaudeBackend()
    with _no_keychain(), _claude_on_path():
        ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is True


@pytest.mark.asyncio
async def test_validate_returns_false_when_credentials_corrupt(tmp_path):
    creds = tmp_path / ".credentials.json"
    creds.write_text("not valid json{{{")
    backend = ClaudeBackend()
    with _no_keychain(), _claude_on_path():
        ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_validate_returns_true_when_macos_keychain_has_entry(tmp_path):
    """On macOS, a populated keychain entry alone is enough (CLI default storage)."""
    fake_ok = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    backend = ClaudeBackend()
    with (
        _claude_on_path(),
        patch("ai_accounts_core.backends.claude.sys.platform", "darwin"),
        patch("ai_accounts_core.backends.claude.subprocess.run", return_value=fake_ok),
    ):
        ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is True


@pytest.mark.asyncio
async def test_list_models_empty_when_no_live_source(tmp_path):
    """No credential and no reachable cliproxy → empty list, not a curated
    static set. Force the live path to 'unavailable' so the test machine's
    real cliproxyapi (if any) doesn't shadow the result.

    v0.7.11 added keychain/.credentials.json fallbacks for the empty-
    credential case, so we also stub those helpers — otherwise this test
    runs against the developer's real keychain on macOS and reaches the
    live Anthropic /v1/models response (which has no context_window)."""
    from unittest.mock import AsyncMock as _AsyncMock

    backend = ClaudeBackend()
    with (
        patch(
            "ai_accounts_core.cliproxy.cliproxy_list_models",
            new=_AsyncMock(return_value=None),
        ),
        patch.object(
            ClaudeBackend,
            "_try_macos_keychain_oauth_token",
            new=_AsyncMock(return_value=None),
        ),
        patch.object(
            ClaudeBackend,
            "_try_credentials_file_oauth_token",
            new=_AsyncMock(return_value=None),
        ),
    ):
        models = await backend.list_models(b"", isolation_dir=tmp_path)
    assert models == []
