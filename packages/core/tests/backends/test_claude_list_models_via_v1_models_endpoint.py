"""Tests for ClaudeBackend.list_models calling /v1/models directly (v0.7.10)."""

from __future__ import annotations

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend


_API_MODELS_RESPONSE = {
    "data": [
        {
            "type": "model",
            "id": "claude-opus-4-7",
            "display_name": "Claude Opus 4.7",
            "created_at": "2026-04-15T00:00:00Z",
        },
        {
            "type": "model",
            "id": "claude-sonnet-4-7",
            "display_name": "Claude Sonnet 4.7",
            "created_at": "2026-04-15T00:00:00Z",
        },
    ]
}


@pytest.mark.asyncio
async def test_api_key_credential_sends_x_api_key_header(tmp_path, httpx_mock):
    """Pure API key (sk-ant-... but not sk-ant-oat-) → x-api-key header."""
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/models",
        match_headers={
            "x-api-key": "sk-ant-abc123",
            "anthropic-version": "2023-06-01",
        },
        json=_API_MODELS_RESPONSE,
    )
    backend = ClaudeBackend()
    models = await backend.list_models(b"sk-ant-abc123", isolation_dir=tmp_path)
    ids = [m.id for m in models]
    assert "claude-opus-4-7" in ids
    assert "claude-sonnet-4-7" in ids


@pytest.mark.asyncio
async def test_oauth_credential_sends_bearer_and_oauth_beta(tmp_path, httpx_mock):
    """OAuth tokens (sk-ant-oat-...) → Authorization: Bearer + oauth-2025-04-20."""
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/models",
        match_headers={
            "Authorization": "Bearer sk-ant-oat-xyz789",
            "anthropic-beta": "oauth-2025-04-20",
        },
        json=_API_MODELS_RESPONSE,
    )
    backend = ClaudeBackend()
    models = await backend.list_models(b"sk-ant-oat-xyz789", isolation_dir=tmp_path)
    ids = [m.id for m in models]
    assert ids == ["claude-opus-4-7", "claude-sonnet-4-7"]


@pytest.mark.asyncio
async def test_non_200_response_falls_through_to_static(tmp_path, httpx_mock, monkeypatch):
    """A 401/403/etc. should drop to the static curated list (no cliproxy)."""
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/models",
        status_code=401,
        json={"error": {"message": "invalid_api_key"}},
    )

    async def _no_cliproxy(_kind: str):
        return None

    monkeypatch.setattr(
        "ai_accounts_core.cliproxy.cliproxy_list_models", _no_cliproxy
    )
    backend = ClaudeBackend()
    models = await backend.list_models(b"sk-ant-abc123", isolation_dir=tmp_path)
    # Static fallback fired — should contain refreshed entries (4.7 family).
    ids = [m.id for m in models]
    assert "claude-opus-4-7" in ids
    assert "claude-sonnet-4-7" in ids


@pytest.mark.asyncio
async def test_empty_credential_falls_through(tmp_path, monkeypatch):
    """cli_browser sessions without a stored bearer must NOT call /v1/models.

    The httpx_mock fixture is intentionally absent — if the helper attempted a
    real network call here, pytest-httpx would fail it; instead we expect a
    direct fall-through to the static curated list.

    v0.7.11 added keychain/.credentials.json fallbacks for cli_browser auth,
    so we stub both helpers to return None to preserve the original
    "no-bearer → no /v1/models call → static list" assertion.
    """

    async def _no_cliproxy(_kind: str):
        return None

    async def _no_keychain(self):
        return None

    async def _no_creds_file(self, _iso):
        return None

    monkeypatch.setattr(
        "ai_accounts_core.cliproxy.cliproxy_list_models", _no_cliproxy
    )
    monkeypatch.setattr(
        ClaudeBackend, "_try_macos_keychain_oauth_token", _no_keychain
    )
    monkeypatch.setattr(
        ClaudeBackend, "_try_credentials_file_oauth_token", _no_creds_file
    )
    backend = ClaudeBackend()
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    assert models  # static list, non-empty
    assert all(m.id.startswith("claude-") for m in models)
