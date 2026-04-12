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
async def test_validate_with_api_key_sets_env(tmp_path: Path):
    backend = CodexBackend()
    isolation_dir = tmp_path / "codex"
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"sk-test-key", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert spec["env"]["OPENAI_API_KEY"] == "sk-test-key"
    assert spec["env"]["CODEX_HOME"] == str(isolation_dir)


@pytest.mark.asyncio
async def test_validate_with_empty_credential_omits_api_key_env(tmp_path: Path):
    backend = CodexBackend()
    isolation_dir = tmp_path / "codex"
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert "OPENAI_API_KEY" not in spec["env"]
    assert spec["env"]["CODEX_HOME"] == str(isolation_dir)


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
