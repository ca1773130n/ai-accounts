import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.opencode import OpenCodeBackend
from ai_accounts_core.protocols.backend import (
    CredentialLogin,
    LoginError,
    LoginFlow,
)


@pytest.mark.asyncio
async def test_detect_finds_cli():
    backend = OpenCodeBackend()
    with patch("shutil.which", return_value="/opt/bin/opencode"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"opencode 0.4.2\n", b""))):
        result = await backend.detect()
    assert result.installed is True
    assert result.version is not None
    assert "opencode" in result.version.lower()


@pytest.mark.asyncio
async def test_login_api_key_returns_credential_login(tmp_path: Path):
    backend = OpenCodeBackend()
    result = await backend.login(
        LoginFlow(kind="api_key", inputs={"api_key": "oc-abc"}),
        isolation_dir=tmp_path / "opencode",
    )
    assert isinstance(result, CredentialLogin)
    assert result.credential == b"oc-abc"


@pytest.mark.asyncio
async def test_login_api_key_strips_whitespace(tmp_path: Path):
    backend = OpenCodeBackend()
    result = await backend.login(
        LoginFlow(kind="api_key", inputs={"api_key": "  oc-xyz  \n"}),
        isolation_dir=tmp_path / "opencode",
    )
    assert isinstance(result, CredentialLogin)
    assert result.credential == b"oc-xyz"


@pytest.mark.asyncio
async def test_login_missing_api_key_returns_error(tmp_path: Path):
    backend = OpenCodeBackend()
    result = await backend.login(
        LoginFlow(kind="api_key", inputs={}),
        isolation_dir=tmp_path / "opencode",
    )
    assert isinstance(result, LoginError)
    assert result.code == "missing_input"


@pytest.mark.asyncio
async def test_login_unsupported_flow_returns_error(tmp_path: Path):
    backend = OpenCodeBackend()
    result = await backend.login(
        LoginFlow(kind="oauth_device", inputs={}),
        isolation_dir=tmp_path / "opencode",
    )
    assert isinstance(result, LoginError)
    assert result.code == "unsupported_flow"


@pytest.mark.asyncio
async def test_poll_login_not_pollable(tmp_path: Path):
    backend = OpenCodeBackend()
    result = await backend.poll_login("x", isolation_dir=tmp_path / "opencode")
    assert isinstance(result, LoginError)
    assert result.code == "not_pollable"


def test_supported_login_flows_is_api_key_only():
    assert OpenCodeBackend.supported_login_flows == frozenset({"api_key"})


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
