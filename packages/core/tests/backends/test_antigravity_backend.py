from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.backends.antigravity import AntigravityBackend


@pytest.mark.asyncio
async def test_detect_is_keyless():
    # Google deprecated the Antigravity CLI in favour of Antigravity; auth runs
    # through cliproxyapi's `-antigravity-login`, so there is no local binary
    # to probe. detect() always reports available with a "No CLI required"
    # note regardless of whether a legacy `antigravity` binary is on PATH.
    backend = AntigravityBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.detect()
    assert result.installed is True
    assert result.notes == "No CLI required"


def test_supported_login_flows():
    # cli_browser delegates to cliproxyapi --login (Google account /
    # Antigravity Code Assist subscription). api_key remains for users who
    # want direct AI Studio access without a subscription.
    assert AntigravityBackend.supported_login_flows == frozenset({"cli_browser", "api_key"})


def test_kind_is_antigravity():
    assert AntigravityBackend.kind == "antigravity"


def _no_cliproxy():
    """Force the cliproxy fallback to 'unavailable' so the test machine's
    real cliproxyapi (if running) doesn't shadow the assertions."""
    return patch(
        "ai_accounts_core.cliproxy.cliproxy_list_models",
        new=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_validate_returns_false_for_empty_credential(tmp_path: Path):
    backend = AntigravityBackend()
    with _no_cliproxy():
        ok = await backend.validate(b"", isolation_dir=tmp_path / "antigravity")
    assert ok is False


@pytest.mark.asyncio
async def test_validate_returns_true_when_cliproxy_lists_antigravity(tmp_path: Path):
    """cli_browser flow leaves credential empty — validation succeeds when
    cliproxyapi confirms it has antigravity providers registered."""
    backend = AntigravityBackend()
    fake = [{"id": "antigravity-2.5-pro", "owned_by": "google"}]
    with patch(
        "ai_accounts_core.cliproxy.cliproxy_list_models",
        new=AsyncMock(return_value=fake),
    ):
        ok = await backend.validate(b"", isolation_dir=tmp_path / "antigravity")
    assert ok is True


@pytest.mark.asyncio
async def test_validate_calls_google_api_with_key(tmp_path: Path):
    """validate() must hit Google AI Studio /models with the key, not the CLI."""

    backend = AntigravityBackend()
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

        async def get(self, url, *, headers=None, **_):
            captured["url"] = url
            captured["headers"] = headers or {}
            return _Resp()

    from ai_accounts_core.backends import antigravity as antigravity_mod

    with patch.object(antigravity_mod.httpx, "AsyncClient", _Client):
        ok = await backend.validate(b"AIzaSy-test", isolation_dir=tmp_path / "antigravity")
    assert ok is True
    assert captured["url"].endswith("/v1beta/models")
    assert captured["headers"].get("x-goog-api-key") == "AIzaSy-test"


@pytest.mark.asyncio
async def test_list_models_parses_google_payload(tmp_path: Path):
    backend = AntigravityBackend()

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {
                        "name": "models/antigravity-2.5-pro",
                        "displayName": "Antigravity 2.5 Pro",
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

    from ai_accounts_core.backends import antigravity as antigravity_mod

    with patch.object(antigravity_mod.httpx, "AsyncClient", _Client):
        models = await backend.list_models(b"AIzaSy-test", isolation_dir=tmp_path / "antigravity")
    assert len(models) == 1
    assert models[0].id == "antigravity-2.5-pro"
    assert models[0].context_window == 2_000_000


@pytest.mark.asyncio
async def test_begin_login_cli_browser_returns_cliproxy_session(tmp_path: Path):
    """The cli_browser flow_kind should construct a _AntigravityCliProxySession."""
    from ai_accounts_core.backends.antigravity import _AntigravityCliProxySession

    backend = AntigravityBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={"backend_id": "x", "kind": "antigravity"},
        isolation_dir=tmp_path / "antigravity",
    )
    assert isinstance(session, _AntigravityCliProxySession)
    assert session.backend_kind == "antigravity"
    assert session.flow_kind == "cli_browser"
    assert session.done is False


@pytest.mark.asyncio
async def test_cliproxy_session_yields_url_and_text_prompt(tmp_path: Path):
    """Happy path: cliproxy returns an OAuth URL → session yields UrlPrompt
    + TextPrompt (paste callback URL)."""
    from ai_accounts_core.backends.antigravity import _AntigravityCliProxySession
    from ai_accounts_core.cliproxy.manager import CliproxyLoginInfo
    from ai_accounts_core.login import TextPrompt, UrlPrompt

    fake_info = CliproxyLoginInfo(oauth_url="https://accounts.google.com/o/oauth2/auth?x=1")
    with patch(
        "ai_accounts_core.cliproxy.start_cliproxy_login",
        new=AsyncMock(return_value=(None, fake_info)),
    ):
        session = _AntigravityCliProxySession()
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
    from ai_accounts_core.backends.antigravity import _AntigravityCliProxySession
    from ai_accounts_core.cliproxy.manager import CliproxyLoginInfo
    from ai_accounts_core.login import LoginFailed

    fake_info = CliproxyLoginInfo(error="cliproxyapi binary not found")
    with patch(
        "ai_accounts_core.cliproxy.start_cliproxy_login",
        new=AsyncMock(return_value=(None, fake_info)),
    ):
        session = _AntigravityCliProxySession()
        events = [ev async for ev in session.events()]
    assert len(events) == 1
    assert isinstance(events[0], LoginFailed)
    assert events[0].code == "cliproxy_unavailable"
