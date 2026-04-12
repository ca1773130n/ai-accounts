import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.protocols.backend import ChatRequest, PtyRequest


@pytest.mark.asyncio
async def test_detect_finds_cli():
    backend = ClaudeBackend()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"claude-cli/1.2.3\n", b""))):
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
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"err"))):
        result = await backend.detect()
    assert result.installed is True
    assert result.path == "/usr/local/bin/claude"
    assert result.version is None
    assert "version" in (result.notes or "").lower()


def test_supported_login_flows_includes_api_key_and_cli_browser():
    assert "api_key" in ClaudeBackend.supported_login_flows
    assert "cli_browser" in ClaudeBackend.supported_login_flows


@pytest.mark.asyncio
async def test_validate_succeeds_on_rc_zero(tmp_path: Path):
    backend = ClaudeBackend()
    isolation_dir = tmp_path / "claude"
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"sk-ant-test", isolation_dir=isolation_dir)
    assert result is True
    called_spec = mock_run.await_args.args[0]
    assert called_spec["env"]["ANTHROPIC_API_KEY"] == "sk-ant-test"


@pytest.mark.asyncio
async def test_validate_uses_isolation_dir_in_env(tmp_path: Path):
    backend = ClaudeBackend()
    isolation_dir = tmp_path / "claude"
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"sk-ant-test", isolation_dir=isolation_dir)
    assert result is True
    assert isolation_dir.exists()
    spec = mock_run.await_args.args[0]
    assert spec["env"]["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert spec["env"]["CLAUDE_CONFIG_DIR"] == str(isolation_dir)


@pytest.mark.asyncio
async def test_validate_fails_on_nonzero_rc(tmp_path: Path):
    backend = ClaudeBackend()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"invalid api key"))):
        result = await backend.validate(b"bad", isolation_dir=tmp_path / "claude")
    assert result is False


@pytest.mark.asyncio
async def test_validate_missing_cli_returns_false(tmp_path: Path):
    backend = ClaudeBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.validate(b"sk-ant-test", isolation_dir=tmp_path / "claude")
    assert result is False


@pytest.mark.asyncio
async def test_list_models_parses_cli_json(tmp_path: Path):
    backend = ClaudeBackend()
    payload = json.dumps([
        {"id": "claude-opus-4-6", "display_name": "Claude Opus 4.6", "context_window": 1_000_000},
        {"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "context_window": 200_000},
    ]).encode()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, payload, b""))):
        models = await backend.list_models(b"sk-ant-test", isolation_dir=tmp_path / "claude")
    ids = {m.id for m in models}
    assert ids == {"claude-opus-4-6", "claude-sonnet-4-6"}


@pytest.mark.asyncio
async def test_list_models_returns_empty_on_error(tmp_path: Path):
    backend = ClaudeBackend()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"err"))):
        models = await backend.list_models(b"sk-ant-test", isolation_dir=tmp_path / "claude")
    assert models == []


@pytest.mark.asyncio
async def test_list_models_missing_cli_returns_empty(tmp_path: Path):
    backend = ClaudeBackend()
    with patch("shutil.which", return_value=None):
        models = await backend.list_models(b"sk-ant-test", isolation_dir=tmp_path / "claude")
    assert models == []



# chat() and pty() are now implemented — see test_claude_chat.py and test_pty_spawn.py
