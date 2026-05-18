import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.backends.opencode import OpenCodeBackend


@pytest.mark.asyncio
async def test_detect_finds_cli():
    backend = OpenCodeBackend()
    with (
        patch("shutil.which", return_value="/opt/bin/opencode"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"opencode 0.4.2\n", b""))),
    ):
        result = await backend.detect()
    assert result.installed is True
    assert result.version is not None
    assert "opencode" in result.version.lower()


def test_supported_login_flows_includes_api_key_and_cli_browser():
    assert "api_key" in OpenCodeBackend.supported_login_flows
    assert "cli_browser" in OpenCodeBackend.supported_login_flows


@pytest.mark.asyncio
async def test_validate_uses_providers_list_subcommand(tmp_path: Path):
    """opencode 0.x has no `auth check`; the real subcommand is
    `providers list`. Validate must pick that path."""
    backend = OpenCodeBackend()
    isolation_dir = tmp_path / "opencode"
    with (
        patch("shutil.which", return_value="/opt/bin/opencode"),
        patch.object(
            backend,
            "_run",
            new=AsyncMock(
                return_value=(0, b"Credentials\n  3 credentials\n", b""),
            ),
        ) as mock_run,
    ):
        result = await backend.validate(b"oc-abc", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert spec["argv"][1:] == ["providers", "list"]
    assert spec["env"]["OPENCODE_API_KEY"] == "oc-abc"


@pytest.mark.asyncio
async def test_validate_returns_false_for_zero_credentials(tmp_path: Path):
    backend = OpenCodeBackend()
    with (
        patch("shutil.which", return_value="/opt/bin/opencode"),
        patch.object(
            backend,
            "_run",
            new=AsyncMock(
                return_value=(0, b"Credentials\n  0 credentials\n", b""),
            ),
        ),
    ):
        result = await backend.validate(b"", isolation_dir=tmp_path / "opencode")
    assert result is False


@pytest.mark.asyncio
async def test_validate_fails_on_nonzero_rc(tmp_path: Path):
    backend = OpenCodeBackend()
    with (
        patch("shutil.which", return_value="/opt/bin/opencode"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"err"))),
    ):
        result = await backend.validate(b"bad", isolation_dir=tmp_path / "opencode")
    assert result is False


@pytest.mark.asyncio
async def test_validate_missing_cli_returns_false(tmp_path: Path):
    backend = OpenCodeBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.validate(b"oc-abc", isolation_dir=tmp_path / "opencode")
    assert result is False


def _openrouter_unavailable():
    """Force the OpenRouter live-discovery probe to fail so the CLI fallback
    path runs deterministically (the test machine may have working internet
    that would otherwise return a real model list)."""

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **kw):
            import httpx as _httpx

            raise _httpx.ConnectError("no network in test")

    return patch("ai_accounts_core.backends.opencode.httpx.AsyncClient", _FakeClient)


@pytest.mark.asyncio
async def test_list_models_parses(tmp_path: Path):
    backend = OpenCodeBackend()
    payload = json.dumps(
        [
            {"id": "opencode-default", "display_name": "OpenCode Default"},
        ]
    ).encode()
    with (
        _openrouter_unavailable(),
        patch("shutil.which", return_value="/opt/bin/opencode"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(0, payload, b""))),
    ):
        models = await backend.list_models(b"oc-abc", isolation_dir=tmp_path / "opencode")
    assert len(models) == 1
    assert models[0].id == "opencode-default"


@pytest.mark.asyncio
async def test_list_models_returns_empty_on_error(tmp_path: Path):
    backend = OpenCodeBackend()
    with (
        _openrouter_unavailable(),
        patch("shutil.which", return_value="/opt/bin/opencode"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(1, b"", b"err"))),
    ):
        models = await backend.list_models(b"oc-abc", isolation_dir=tmp_path / "opencode")
    assert models == []


@pytest.mark.asyncio
async def test_list_models_uses_openrouter_when_api_key_present(tmp_path: Path):
    """With a working api_key, the OpenRouter probe wins over the CLI."""
    backend = OpenCodeBackend()

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "data": [
                    {
                        "id": "anthropic/claude-3.5-sonnet",
                        "name": "Claude 3.5 Sonnet",
                        "context_length": 200000,
                    },
                    {"id": "openai/gpt-4o", "name": "GPT-4o", "context_length": 128000},
                ]
            }

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **kw):
            return _FakeResp()

    async def explode(*a, **kw):
        raise AssertionError("CLI _run should NOT be called when openrouter answers")

    with (
        patch("ai_accounts_core.backends.opencode.httpx.AsyncClient", _FakeClient),
        patch.object(backend, "_run", side_effect=explode),
    ):
        models = await backend.list_models(b"oc-abc", isolation_dir=tmp_path / "opencode")
    ids = [m.id for m in models]
    assert ids == ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"]
    assert models[0].context_window == 200000
