from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.gemini import GeminiBackend


@pytest.mark.asyncio
async def test_detect_finds_cli():
    backend = GeminiBackend()
    with patch("shutil.which", return_value="/usr/local/bin/gemini"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"gemini-cli 1.0.0\n", b""))):
        result = await backend.detect()
    assert result.installed is True
    assert "gemini" in (result.version or "").lower()


@pytest.mark.asyncio
async def test_detect_missing_cli():
    backend = GeminiBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.detect()
    assert result.installed is False


def test_supported_login_flows():
    assert "api_key" in GeminiBackend.supported_login_flows
    assert "oauth_device" in GeminiBackend.supported_login_flows


def test_kind_is_gemini():
    assert GeminiBackend.kind == "gemini"


@pytest.mark.asyncio
async def test_validate_with_api_key_sets_env(tmp_path: Path):
    backend = GeminiBackend()
    isolation_dir = tmp_path / "gemini"
    with patch("shutil.which", return_value="/usr/local/bin/gemini"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"AIzaSy-test", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert spec["env"]["GEMINI_API_KEY"] == "AIzaSy-test"
    assert spec["env"]["GEMINI_CLI_HOME"] == str(isolation_dir)


@pytest.mark.asyncio
async def test_validate_with_empty_credential_omits_api_key_env(tmp_path: Path):
    backend = GeminiBackend()
    isolation_dir = tmp_path / "gemini"
    with patch("shutil.which", return_value="/usr/local/bin/gemini"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert "GEMINI_API_KEY" not in spec["env"]
    assert spec["env"]["GEMINI_CLI_HOME"] == str(isolation_dir)


@pytest.mark.asyncio
async def test_list_models_parses_json(tmp_path: Path):
    import json as _json
    backend = GeminiBackend()
    payload = _json.dumps([
        {"id": "gemini-2-5-pro", "display_name": "Gemini 2.5 Pro", "context_window": 2_000_000},
    ]).encode()
    with patch("shutil.which", return_value="/usr/local/bin/gemini"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, payload, b""))):
        models = await backend.list_models(b"", isolation_dir=tmp_path / "gemini")
    assert len(models) == 1
    assert models[0].id == "gemini-2-5-pro"
