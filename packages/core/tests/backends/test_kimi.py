from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from ai_accounts_core.backends.kimi import KimiBackend, _KimiCliProxySession
from ai_accounts_core.login.events import (
    LoginComplete,
    PromptAnswer,
    UrlPrompt,
)


async def _drain(session):
    return [evt async for evt in session.events()]


def test_kimi_metadata_shape():
    meta = KimiBackend.metadata
    assert meta.kind == "kimi"
    assert meta.display_name == "Kimi (Moonshot)"
    assert meta.supports_multi_account is True
    # Single cli_browser OAuth flow (delegated to cliproxyapi -kimi-login).
    flow_kinds = {f.kind for f in meta.login_flows}
    assert flow_kinds == {"cli_browser"}
    assert KimiBackend.supported_login_flows == frozenset({"cli_browser"})


def test_kimi_session_kinds():
    session = _KimiCliProxySession()
    assert session.backend_kind == "kimi"
    assert session.flow_kind == "cli_browser"


@pytest.mark.asyncio
async def test_kimi_detect_is_keyless():
    # Keyless backend — no CLI binary to probe; always available.
    result = await KimiBackend().detect()
    assert result.installed is True


@pytest.mark.asyncio
async def test_kimi_begin_login_rejects_unknown_flow(tmp_path: Path):
    backend = KimiBackend()
    with pytest.raises(ValueError, match="unsupported"):
        backend.begin_login(
            flow_kind="api_key",
            config={},
            vault_ctx={},
            isolation_dir=tmp_path,
        )


@pytest.mark.asyncio
async def test_kimi_cli_browser_drives_cliproxy_with_kimi(monkeypatch, tmp_path: Path):
    """begin_login("cli_browser") returns the cliproxy session, which calls
    start_cliproxy_login with the "kimi" backend kind."""
    from ai_accounts_core.cliproxy import manager

    called: list[str] = []

    class _FakeInfo:
        error = None
        imported = True  # short-circuit to LoginComplete (cached credential)
        oauth_url = None
        fake_dir = None

    async def _fake_start(backend_kind, *args, **kwargs):
        called.append(backend_kind)
        return None, _FakeInfo()

    # Session imports start_cliproxy_login from ai_accounts_core.cliproxy,
    # which re-exports manager.start_cliproxy_login — patch at the source.
    monkeypatch.setattr(manager, "start_cliproxy_login", _fake_start)
    import ai_accounts_core.cliproxy as cliproxy_pkg

    monkeypatch.setattr(cliproxy_pkg, "start_cliproxy_login", _fake_start)

    backend = KimiBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )
    assert isinstance(session, _KimiCliProxySession)

    events = await asyncio.wait_for(_drain(session), timeout=5)

    assert called == ["kimi"]
    assert any(isinstance(e, LoginComplete) for e in events)


@pytest.mark.asyncio
async def test_kimi_cli_browser_yields_oauth_url(monkeypatch, tmp_path: Path):
    """When cliproxy produces an OAuth URL, the session surfaces it as a
    UrlPrompt before waiting for the pasted callback."""
    from ai_accounts_core.cliproxy import manager

    class _FakeInfo:
        error = None
        imported = False
        oauth_url = "https://example.com/oauth/kimi"
        fake_dir = None

    async def _fake_start(backend_kind, *args, **kwargs):
        assert backend_kind == "kimi"
        return None, _FakeInfo()

    async def _fake_forward(answer):
        return {"status": "completed"}

    monkeypatch.setattr(manager, "start_cliproxy_login", _fake_start)
    import ai_accounts_core.cliproxy as cliproxy_pkg

    monkeypatch.setattr(cliproxy_pkg, "start_cliproxy_login", _fake_start)
    monkeypatch.setattr(manager, "forward_cliproxy_callback", _fake_forward)
    monkeypatch.setattr(cliproxy_pkg, "forward_cliproxy_callback", _fake_forward)

    backend = KimiBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="callback", answer="https://localhost/cb?code=x"))
    events = await asyncio.wait_for(events_task, timeout=5)

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert len(url_prompts) == 1
    assert url_prompts[0].url == "https://example.com/oauth/kimi"
    assert any(isinstance(e, LoginComplete) for e in events)
