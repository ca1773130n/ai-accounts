import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.opencode import OpenCodeBackend


@pytest.mark.asyncio
async def test_detect_finds_cli():
    backend = OpenCodeBackend()
    with patch("shutil.which", return_value="/opt/bin/opencode"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"opencode 0.4.2\n", b""))):
        result = await backend.detect()
    assert result.installed is True
    assert result.version is not None
    assert "opencode" in result.version.lower()


def test_supported_login_flows_includes_api_key_and_cli_browser():
    assert "api_key" in OpenCodeBackend.supported_login_flows
    assert "cli_browser" in OpenCodeBackend.supported_login_flows


@pytest.mark.asyncio
async def test_validate_uses_opencode_api_key_env(tmp_path: Path):
    backend = OpenCodeBackend()
    isolation_dir = tmp_path / "opencode"
    with patch("shutil.which", return_value="/opt/bin/opencode"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"oc-abc", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert spec["env"]["OPENCODE_API_KEY"] == "oc-abc"
    assert spec["env"]["OPENCODE_HOME"] == str(isolation_dir)
    assert "auth" in spec["argv"]
    assert "check" in spec["argv"]


@pytest.mark.asyncio
async def test_validate_fails_on_nonzero_rc(tmp_path: Path):
    backend = OpenCodeBackend()
    with patch("shutil.which", return_value="/opt/bin/opencode"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"err"))):
        result = await backend.validate(b"bad", isolation_dir=tmp_path / "opencode")
    assert result is False


@pytest.mark.asyncio
async def test_validate_missing_cli_returns_false(tmp_path: Path):
    backend = OpenCodeBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.validate(b"oc-abc", isolation_dir=tmp_path / "opencode")
    assert result is False


@pytest.mark.asyncio
async def test_list_models_parses(tmp_path: Path):
    backend = OpenCodeBackend()
    payload = json.dumps([
        {"id": "opencode-default", "display_name": "OpenCode Default"},
    ]).encode()
    with patch("shutil.which", return_value="/opt/bin/opencode"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, payload, b""))):
        models = await backend.list_models(b"oc-abc", isolation_dir=tmp_path / "opencode")
    assert len(models) == 1
    assert models[0].id == "opencode-default"


@pytest.mark.asyncio
async def test_list_models_returns_empty_on_error(tmp_path: Path):
    backend = OpenCodeBackend()
    with patch("shutil.which", return_value="/opt/bin/opencode"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"err"))):
        models = await backend.list_models(b"oc-abc", isolation_dir=tmp_path / "opencode")
    assert models == []
