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
async def test_list_models_returns_static_set(tmp_path: Path):
    """When every live source is unavailable, list_models() returns the
    static curated fallback.

    list_models() walks four sources before the static set:
      1. ~/.codex/models_cache.json or <isolation>/models_cache.json
      2. Direct OpenAI /v1/models with the credential
      3. CLIProxyAPI live list
      4. Static fallback (asserted here)
    All three must be mocked off so the test isn't shadowed by a real
    cache or network on the dev machine.
    """
    from unittest.mock import AsyncMock as _AsyncMock
    backend = CodexBackend()
    with patch(
        "ai_accounts_core.backends.codex.CodexBackend._list_models_from_codex_cache",
        return_value=None,
    ), patch.object(
        backend,
        "_list_models_via_provider_api",
        new=_AsyncMock(return_value=[]),
    ), patch(
        "ai_accounts_core.cliproxy.cliproxy_list_models",
        new=_AsyncMock(return_value=None),
    ):
        models = await backend.list_models(b"", isolation_dir=tmp_path / "codex")
    ids = {m.id for m in models}
    # gpt-5-codex is the canonical codex CLI default and must always be present.
    assert "gpt-5-codex" in ids
    assert all(m.context_window for m in models)
