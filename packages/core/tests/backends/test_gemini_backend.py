from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.backends.gemini import GeminiBackend


@pytest.mark.asyncio
async def test_detect_is_keyless():
    # Google deprecated the Gemini CLI in favour of Antigravity; auth runs
    # through cliproxyapi's `-antigravity-login`, so there is no local binary
    # to probe. detect() always reports available with a "No CLI required"
    # note regardless of whether a legacy `gemini` binary is on PATH.
    backend = GeminiBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.detect()
    assert result.installed is True
    assert result.notes == "No CLI required"


def test_supported_login_flows():
    # cli_browser delegates to cliproxyapi --login (Google account /
    # Gemini Code Assist subscription). api_key remains for users who
    # want direct AI Studio access without a subscription.
    assert GeminiBackend.supported_login_flows == frozenset({"cli_browser", "api_key"})


def test_kind_is_gemini():
    assert GeminiBackend.kind == "gemini"


def _no_cliproxy():
    """Force the cliproxy fallback to 'unavailable' so the test machine's
    real cliproxyapi (if running) doesn't shadow the assertions."""
    return patch(
        "ai_accounts_core.cliproxy.cliproxy_list_models",
        new=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_validate_returns_false_for_empty_credential(tmp_path: Path):
    backend = GeminiBackend()
    with _no_cliproxy():
        ok = await backend.validate(b"", isolation_dir=tmp_path / "gemini")
    assert ok is False


@pytest.mark.asyncio
async def test_validate_returns_true_when_cliproxy_lists_gemini(tmp_path: Path):
    """cli_browser flow leaves credential empty — validation succeeds when
    cliproxyapi confirms it has gemini providers registered."""
    backend = GeminiBackend()
    fake = [{"id": "gemini-2.5-pro", "owned_by": "google"}]
    with patch(
        "ai_accounts_core.cliproxy.cliproxy_list_models",
        new=AsyncMock(return_value=fake),
    ):
        ok = await backend.validate(b"", isolation_dir=tmp_path / "gemini")
    assert ok is True


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


@pytest.mark.asyncio
async def test_begin_login_cli_browser_returns_cliproxy_session(tmp_path: Path):
    """The cli_browser flow_kind should construct a _GeminiCliProxySession."""
    from ai_accounts_core.backends.gemini import _GeminiCliProxySession

    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={"backend_id": "x", "kind": "gemini"},
        isolation_dir=tmp_path / "gemini",
    )
    assert isinstance(session, _GeminiCliProxySession)
    assert session.backend_kind == "gemini"
    assert session.flow_kind == "cli_browser"
    assert session.done is False


@pytest.mark.asyncio
async def test_cliproxy_session_yields_url_and_text_prompt(tmp_path: Path):
    """Happy path: cliproxy returns an OAuth URL → session yields UrlPrompt
    + TextPrompt (paste callback URL)."""
    from ai_accounts_core.backends.gemini import _GeminiCliProxySession
    from ai_accounts_core.cliproxy.manager import CliproxyLoginInfo
    from ai_accounts_core.login import TextPrompt, UrlPrompt

    fake_info = CliproxyLoginInfo(oauth_url="https://accounts.google.com/o/oauth2/auth?x=1")
    with patch(
        "ai_accounts_core.cliproxy.start_cliproxy_login",
        new=AsyncMock(return_value=(None, fake_info)),
    ):
        session = _GeminiCliProxySession()
        events = []
        async for ev in session.events():
            events.append(ev)
            if isinstance(ev, TextPrompt):
                break  # waiting for respond — test stops here
    assert len(events) == 2
    assert isinstance(events[0], UrlPrompt)
    assert events[0].url.startswith("https://accounts.google.com/")
    assert isinstance(events[1], TextPrompt)
    assert events[1].prompt_id == "callback"


@pytest.mark.asyncio
async def test_cliproxy_session_failed_when_proxy_unavailable(tmp_path: Path):
    """If cliproxyapi isn't installed, the session yields LoginFailed."""
    from ai_accounts_core.backends.gemini import _GeminiCliProxySession
    from ai_accounts_core.cliproxy.manager import CliproxyLoginInfo
    from ai_accounts_core.login import LoginFailed

    fake_info = CliproxyLoginInfo(error="cliproxyapi binary not found")
    with patch(
        "ai_accounts_core.cliproxy.start_cliproxy_login",
        new=AsyncMock(return_value=(None, fake_info)),
    ):
        session = _GeminiCliProxySession()
        events = [ev async for ev in session.events()]
    assert len(events) == 1
    assert isinstance(events[0], LoginFailed)
    assert events[0].code == "cliproxy_unavailable"
