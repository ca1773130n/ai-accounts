import json
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.protocols.backend import ChatRequest, LoginFlow, PtyRequest


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


@pytest.mark.asyncio
async def test_login_api_key_returns_plaintext_bytes():
    backend = ClaudeBackend()
    result = await backend.login(LoginFlow(kind="api_key", inputs={"api_key": "sk-ant-abc123"}))
    assert result == b"sk-ant-abc123"


@pytest.mark.asyncio
async def test_login_api_key_strips_whitespace():
    backend = ClaudeBackend()
    result = await backend.login(LoginFlow(kind="api_key", inputs={"api_key": "  sk-ant-x  \n"}))
    assert result == b"sk-ant-x"


@pytest.mark.asyncio
async def test_login_missing_api_key_raises():
    backend = ClaudeBackend()
    with pytest.raises(ValueError, match="api_key"):
        await backend.login(LoginFlow(kind="api_key", inputs={}))


@pytest.mark.asyncio
async def test_login_unknown_flow_raises():
    backend = ClaudeBackend()
    with pytest.raises(ValueError, match="login flow"):
        await backend.login(LoginFlow(kind="oauth_device", inputs={}))


@pytest.mark.asyncio
async def test_validate_succeeds_on_rc_zero():
    backend = ClaudeBackend()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"sk-ant-test")
    assert result is True
    called_spec = mock_run.await_args.args[0]
    assert called_spec["env"]["ANTHROPIC_API_KEY"] == "sk-ant-test"


@pytest.mark.asyncio
async def test_validate_fails_on_nonzero_rc():
    backend = ClaudeBackend()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"invalid api key"))):
        result = await backend.validate(b"bad")
    assert result is False


@pytest.mark.asyncio
async def test_validate_missing_cli_returns_false():
    backend = ClaudeBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.validate(b"sk-ant-test")
    assert result is False


@pytest.mark.asyncio
async def test_list_models_parses_cli_json():
    backend = ClaudeBackend()
    payload = json.dumps([
        {"id": "claude-opus-4-6", "display_name": "Claude Opus 4.6", "context_window": 1_000_000},
        {"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "context_window": 200_000},
    ]).encode()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, payload, b""))):
        models = await backend.list_models(b"sk-ant-test")
    ids = {m.id for m in models}
    assert ids == {"claude-opus-4-6", "claude-sonnet-4-6"}


@pytest.mark.asyncio
async def test_list_models_returns_empty_on_error():
    backend = ClaudeBackend()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"err"))):
        models = await backend.list_models(b"sk-ant-test")
    assert models == []


@pytest.mark.asyncio
async def test_list_models_missing_cli_returns_empty():
    backend = ClaudeBackend()
    with patch("shutil.which", return_value=None):
        models = await backend.list_models(b"sk-ant-test")
    assert models == []


@pytest.mark.asyncio
async def test_chat_not_implemented():
    backend = ClaudeBackend()
    with pytest.raises(NotImplementedError, match="Phase 3"):
        await backend.chat(ChatRequest(messages=(), model="x"), b"cred")


@pytest.mark.asyncio
async def test_pty_not_implemented():
    backend = ClaudeBackend()
    with pytest.raises(NotImplementedError, match="Phase 4"):
        await backend.pty(PtyRequest(command=("claude",), cols=80, rows=24), b"cred")
