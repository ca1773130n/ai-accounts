import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.backends.claude import ClaudeBackend


def _no_keychain():
    """Force the macOS keychain probe in validate() to report 'not found'.

    On developers' macOS the system keychain may have a real Claude entry,
    which would short-circuit validate() to True and mask the file probe
    these tests are exercising. Patch subprocess.run inside the claude
    backend module to always return rc=1.
    """
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"")
    return patch("ai_accounts_core.backends.claude.subprocess.run", return_value=fake)


@pytest.mark.asyncio
async def test_detect_finds_cli():
    backend = ClaudeBackend()
    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"claude-cli/1.2.3\n", b""))),
    ):
        result = await backend.detect()
    assert result.installed is True
    assert result.version == "claude-cli/1.2.3"
    assert result.path == "/usr/local/bin/claude"


@pytest.mark.asyncio
async def test_detect_missing_cli():
    backend = ClaudeBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.detect()
    assert result.installed is False
    assert result.version is None


@pytest.mark.asyncio
async def test_detect_version_command_fails():
    backend = ClaudeBackend()
    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"err"))),
    ):
        result = await backend.detect()
    assert result.installed is True
    assert result.path == "/usr/local/bin/claude"
    assert result.version is None
    assert "version" in (result.notes or "").lower()


def test_supported_login_flows_includes_api_key_and_cli_browser():
    assert "api_key" in ClaudeBackend.supported_login_flows
    assert "cli_browser" in ClaudeBackend.supported_login_flows


@pytest.mark.asyncio
async def test_validate_succeeds_when_credentials_file_present(tmp_path: Path):
    """Claude CLI has no `auth status` subcommand. Validate by checking the
    credentials.json file the CLI writes after a successful /login."""
    backend = ClaudeBackend()
    isolation_dir = tmp_path / "claude"
    isolation_dir.mkdir(parents=True)
    (isolation_dir / ".credentials.json").write_text(json.dumps({"oauth_token": "sk-ant-..."}))
    with patch("shutil.which", return_value="/usr/local/bin/claude"), _no_keychain():
        result = await backend.validate(b"", isolation_dir=isolation_dir)
    assert result is True


@pytest.mark.asyncio
async def test_validate_returns_false_when_credentials_file_missing(tmp_path: Path):
    backend = ClaudeBackend()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), _no_keychain():
        result = await backend.validate(b"", isolation_dir=tmp_path / "claude")
    assert result is False


@pytest.mark.asyncio
async def test_validate_returns_false_when_credentials_corrupt(tmp_path: Path):
    backend = ClaudeBackend()
    isolation_dir = tmp_path / "claude"
    isolation_dir.mkdir(parents=True)
    (isolation_dir / ".credentials.json").write_text("not json{{")
    with patch("shutil.which", return_value="/usr/local/bin/claude"), _no_keychain():
        result = await backend.validate(b"", isolation_dir=isolation_dir)
    assert result is False


@pytest.mark.asyncio
async def test_validate_missing_cli_returns_false(tmp_path: Path):
    backend = ClaudeBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.validate(b"sk-ant-test", isolation_dir=tmp_path / "claude")
    assert result is False


@pytest.mark.asyncio
async def test_list_models_returns_static_set_no_subprocess(tmp_path: Path):
    """Claude CLI has no `models list` subcommand. With cliproxy unavailable
    we return a static set, so list_models must not invoke any subprocess."""
    from unittest.mock import AsyncMock as _AsyncMock

    backend = ClaudeBackend()

    async def explode(spec):
        raise AssertionError(f"_run must not be called by list_models, got {spec}")

    # Force the cliproxy live-discovery path to "unavailable" so the static
    # fallback runs deterministically — the test machine may have a real
    # cliproxyapi running on :8317 which would otherwise win.
    with (
        patch.object(backend, "_run", side_effect=explode),
        patch(
            "ai_accounts_core.cliproxy.cliproxy_list_models",
            new=_AsyncMock(return_value=None),
        ),
        patch(
            "ai_accounts_core.backends._models_fallback.cached_live",
            return_value=None,
        ),
    ):
        models = await backend.list_models(b"sk-ant-test", isolation_dir=tmp_path / "claude")
    ids = {m.id for m in models}
    assert "claude-sonnet-4-6" in ids
    assert all(m.context_window for m in models)


# chat() and pty() are now implemented — see test_claude_chat.py and test_pty_spawn.py
