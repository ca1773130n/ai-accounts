import json

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend


@pytest.mark.asyncio
async def test_validate_returns_false_when_isolation_dir_empty(tmp_path):
    backend = ClaudeBackend()
    ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_validate_returns_true_when_credentials_present(tmp_path):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({"oauth_token": "sk-ant-..."}))
    backend = ClaudeBackend()
    ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is True


@pytest.mark.asyncio
async def test_validate_returns_false_when_credentials_corrupt(tmp_path):
    creds = tmp_path / ".credentials.json"
    creds.write_text("not valid json{{{")
    backend = ClaudeBackend()
    ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is False


@pytest.mark.asyncio
async def test_list_models_returns_known_set(tmp_path):
    backend = ClaudeBackend()
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    ids = {m.id for m in models}
    assert "claude-opus-4-7" in ids or "claude-sonnet-4-6" in ids
    assert all(m.context_window for m in models)
