"""v0.7.10 — refreshed static fallback drops deprecated/non-subscription models.

The static list is the last-resort path inside ``ClaudeBackend.list_models``.
When both the direct ``/v1/models`` call AND the CLIProxyAPI live list are
unavailable (offline, throttled, no proxy installed) the operator console
still needs a sane dropdown — but it must not advertise models the user's
subscription tier can't actually use.
"""

from __future__ import annotations

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend


_DEPRECATED_OR_REMOVED_IDS = {
    "claude-3-7-sonnet-20250219",
    "claude-3-5-haiku-20241022",
    "claude-opus-4-1-20250805",
    "claude-opus-4-20250514",
    "claude-sonnet-4-20250514",
}


def _stub_oauth_fallbacks(monkeypatch):
    """Stub the v0.7.11 keychain/.credentials.json fallbacks so empty-
    credential tests don't accidentally reach the developer's real
    Claude OAuth token via the keychain. Also stub the cached-live
    snapshot path so a developer's previously-populated
    ``~/.ai-accounts/models_cache.json`` can't shadow the static set."""

    async def _no_keychain(self):
        return None

    async def _no_creds_file(self, _iso):
        return None

    monkeypatch.setattr(
        ClaudeBackend, "_try_macos_keychain_oauth_token", _no_keychain
    )
    monkeypatch.setattr(
        ClaudeBackend, "_try_credentials_file_oauth_token", _no_creds_file
    )
    monkeypatch.setattr(
        "ai_accounts_core.backends._models_fallback.cached_live",
        lambda _provider: None,
    )


@pytest.mark.asyncio
async def test_static_fallback_omits_deprecated_ids(tmp_path, monkeypatch):
    """Empty credential + no cliproxy → static list. None of the deprecated ids may appear."""

    async def _no_cliproxy(_kind: str):
        return None

    monkeypatch.setattr(
        "ai_accounts_core.cliproxy.cliproxy_list_models", _no_cliproxy
    )
    _stub_oauth_fallbacks(monkeypatch)

    backend = ClaudeBackend()
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    ids = {m.id for m in models}

    leaked = ids & _DEPRECATED_OR_REMOVED_IDS
    assert not leaked, f"static fallback still advertises deprecated ids: {sorted(leaked)}"


@pytest.mark.asyncio
async def test_static_fallback_includes_current_frontier(tmp_path, monkeypatch):
    """The refreshed static list must include the 4.7 frontier entries."""

    async def _no_cliproxy(_kind: str):
        return None

    monkeypatch.setattr(
        "ai_accounts_core.cliproxy.cliproxy_list_models", _no_cliproxy
    )
    _stub_oauth_fallbacks(monkeypatch)

    backend = ClaudeBackend()
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    ids = {m.id for m in models}

    assert "claude-opus-4-7" in ids
    assert "claude-sonnet-4-7" in ids


@pytest.mark.asyncio
async def test_static_fallback_size_matches_spec(tmp_path, monkeypatch):
    """v0.7.10 spec: list shrinks to 7 current-or-recent-stable entries."""

    async def _no_cliproxy(_kind: str):
        return None

    monkeypatch.setattr(
        "ai_accounts_core.cliproxy.cliproxy_list_models", _no_cliproxy
    )
    _stub_oauth_fallbacks(monkeypatch)

    backend = ClaudeBackend()
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    assert len(models) == 7
