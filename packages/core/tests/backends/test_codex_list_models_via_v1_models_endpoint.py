"""Tests for CodexBackend.list_models calling OpenAI /v1/models directly (v0.7.10)."""

from __future__ import annotations

import pytest
from ai_accounts_core.backends.codex import CodexBackend

_API_MODELS_RESPONSE = {
    "data": [
        {"id": "gpt-5.3-codex", "object": "model", "owned_by": "openai"},
        {"id": "gpt-5.2", "object": "model", "owned_by": "openai"},
        {"id": "gpt-5", "object": "model", "owned_by": "openai"},
    ]
}


def _isolate_local_cache(tmp_path, monkeypatch):
    """Stub the v0.7.12 local-cache discovery so /v1/models tests run cleanly."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "no-home"))
    monkeypatch.setattr(
        CodexBackend,
        "_list_models_from_codex_cache",
        lambda self, isolation_dir: None,
    )


@pytest.mark.asyncio
async def test_api_key_credential_sends_bearer_header(tmp_path, httpx_mock, monkeypatch):
    _isolate_local_cache(tmp_path, monkeypatch)
    httpx_mock.add_response(
        url="https://api.openai.com/v1/models",
        match_headers={"Authorization": "Bearer sk-proj-abc123"},
        json=_API_MODELS_RESPONSE,
    )
    backend = CodexBackend()
    models = await backend.list_models(b"sk-proj-abc123", isolation_dir=tmp_path)
    ids = [m.id for m in models]
    assert ids == ["gpt-5.3-codex", "gpt-5.2", "gpt-5"]


@pytest.mark.asyncio
async def test_chatgpt_oauth_token_sends_bearer_header(tmp_path, httpx_mock, monkeypatch):
    """ChatGPT-OAuth bearer tokens use the same Authorization header."""
    _isolate_local_cache(tmp_path, monkeypatch)
    httpx_mock.add_response(
        url="https://api.openai.com/v1/models",
        match_headers={"Authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.fake.oauth.token"},
        json=_API_MODELS_RESPONSE,
    )
    backend = CodexBackend()
    models = await backend.list_models(
        b"eyJhbGciOiJSUzI1NiJ9.fake.oauth.token", isolation_dir=tmp_path
    )
    assert [m.id for m in models] == ["gpt-5.3-codex", "gpt-5.2", "gpt-5"]


@pytest.mark.asyncio
async def test_non_200_response_falls_through_to_static(tmp_path, httpx_mock, monkeypatch):
    """A 401/403 should drop to the static curated list (no cliproxy)."""
    _isolate_local_cache(tmp_path, monkeypatch)
    httpx_mock.add_response(
        url="https://api.openai.com/v1/models",
        status_code=401,
        json={"error": {"message": "invalid_api_key"}},
    )

    async def _no_cliproxy(_kind: str):
        return None

    monkeypatch.setattr("ai_accounts_core.cliproxy.cliproxy_list_models", _no_cliproxy)
    backend = CodexBackend()
    models = await backend.list_models(b"sk-proj-bad", isolation_dir=tmp_path)
    ids = [m.id for m in models]
    assert any(i.startswith("gpt-5") for i in ids)


@pytest.mark.asyncio
async def test_empty_credential_falls_through(tmp_path, monkeypatch):
    """No stored credential → skip provider API and drop to static."""
    _isolate_local_cache(tmp_path, monkeypatch)

    async def _no_cliproxy(_kind: str):
        return None

    monkeypatch.setattr("ai_accounts_core.cliproxy.cliproxy_list_models", _no_cliproxy)
    backend = CodexBackend()
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    assert models  # static list non-empty
