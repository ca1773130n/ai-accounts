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
    # Gemini CLI 0.35+ has no `auth` subcommand — only api_key flow is
    # supported; the OAuth device / direct PKCE flows were dead code.
    assert GeminiBackend.supported_login_flows == frozenset({"api_key"})


def test_kind_is_gemini():
    assert GeminiBackend.kind == "gemini"


@pytest.mark.asyncio
async def test_validate_returns_false_for_empty_credential(tmp_path: Path):
    backend = GeminiBackend()
    ok = await backend.validate(b"", isolation_dir=tmp_path / "gemini")
    assert ok is False


@pytest.mark.asyncio
async def test_validate_calls_google_api_with_key(tmp_path: Path):
    """validate() must hit Google AI Studio /models with the key, not the CLI."""

    backend = GeminiBackend()
    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"models": []}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url, *, params=None, **_):
            captured["url"] = url
            captured["params"] = params or {}
            return _Resp()

    from ai_accounts_core.backends import gemini as gemini_mod

    with patch.object(gemini_mod.httpx, "AsyncClient", _Client):
        ok = await backend.validate(b"AIzaSy-test", isolation_dir=tmp_path / "gemini")
    assert ok is True
    assert captured["url"].endswith("/v1beta/models")
    assert captured["params"].get("key") == "AIzaSy-test"


@pytest.mark.asyncio
async def test_list_models_parses_google_payload(tmp_path: Path):
    backend = GeminiBackend()

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {
                        "name": "models/gemini-2.5-pro",
                        "displayName": "Gemini 2.5 Pro",
                        "inputTokenLimit": 2_000_000,
                    }
                ]
            }

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **kw):
            return _Resp()

    from ai_accounts_core.backends import gemini as gemini_mod

    with patch.object(gemini_mod.httpx, "AsyncClient", _Client):
        models = await backend.list_models(b"AIzaSy-test", isolation_dir=tmp_path / "gemini")
    assert len(models) == 1
    assert models[0].id == "gemini-2.5-pro"
    assert models[0].context_window == 2_000_000
