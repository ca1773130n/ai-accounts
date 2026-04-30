from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.codex import CodexBackend


@pytest.mark.asyncio
async def test_detect_finds_cli():
    backend = CodexBackend()
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"codex 1.0.0\n", b""))):
        result = await backend.detect()
    assert result.installed is True
    assert "codex" in (result.version or "").lower()


@pytest.mark.asyncio
async def test_detect_missing_cli():
    backend = CodexBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.detect()
    assert result.installed is False


def test_supported_login_flows():
    assert "api_key" in CodexBackend.supported_login_flows
    assert "oauth_device" in CodexBackend.supported_login_flows


def test_kind_is_codex():
    assert CodexBackend.kind == "codex"


@pytest.mark.asyncio
async def test_validate_succeeds_when_logged_in_marker_in_stdout(tmp_path: Path):
    """codex 0.121+ uses `login status` (not `auth status`) which exits 0
    even when not logged in — must inspect stdout."""
    backend = CodexBackend()
    isolation_dir = tmp_path / "codex"
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(
             return_value=(0, b"Logged in using ChatGPT\n", b""),
         )) as mock_run:
        result = await backend.validate(b"sk-test-key", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert spec["argv"][1:] == ["login", "status"]
    assert spec["env"]["OPENAI_API_KEY"] == "sk-test-key"


@pytest.mark.asyncio
async def test_validate_returns_false_when_not_logged_in(tmp_path: Path):
    backend = CodexBackend()
    isolation_dir = tmp_path / "codex"
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(
             return_value=(0, b"Not logged in\n", b""),
         )):
        result = await backend.validate(b"", isolation_dir=isolation_dir)
    assert result is False


@pytest.mark.asyncio
async def test_list_models_parses_json(tmp_path: Path):
    import json as _json
    backend = CodexBackend()
    payload = _json.dumps([
        {"id": "gpt-4o", "display_name": "GPT-4o", "context_window": 128_000},
    ]).encode()
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, payload, b""))):
        models = await backend.list_models(b"", isolation_dir=tmp_path / "codex")
    assert len(models) == 1
    assert models[0].id == "gpt-4o"
