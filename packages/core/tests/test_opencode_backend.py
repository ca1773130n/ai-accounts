import json
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.opencode import OpenCodeBackend
from ai_accounts_core.protocols.backend import LoginFlow


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
async def test_login_api_key():
    backend = OpenCodeBackend()
    result = await backend.login(LoginFlow(kind="api_key", inputs={"api_key": "oc-abc"}))
    assert result == b"oc-abc"


@pytest.mark.asyncio
async def test_validate_uses_opencode_api_key_env():
    backend = OpenCodeBackend()
    with patch("shutil.which", return_value="/opt/bin/opencode"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"oc-abc")
    assert result is True
    spec = mock_run.await_args.args[0]
    assert spec["env"]["OPENCODE_API_KEY"] == "oc-abc"
    assert "auth" in spec["argv"]
    assert "check" in spec["argv"]


@pytest.mark.asyncio
async def test_list_models_parses():
    backend = OpenCodeBackend()
    payload = json.dumps([
        {"id": "opencode-default", "display_name": "OpenCode Default"},
    ]).encode()
    with patch("shutil.which", return_value="/opt/bin/opencode"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, payload, b""))):
        models = await backend.list_models(b"oc-abc")
    assert len(models) == 1
    assert models[0].id == "opencode-default"
