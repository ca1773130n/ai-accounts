from __future__ import annotations

import pytest
from ai_accounts_core.backends.claude import ClaudeBackend


@pytest.mark.asyncio
async def test_claude_usage_with_oauth_token(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://api.anthropic.com/api/oauth/usage",
        json={
            "windows": [
                {
                    "window_type": "five_hour",
                    "utilization": 42.5,
                    "resets_at": "2026-04-12T20:00:00+00:00",
                }
            ]
        },
    )
    backend = ClaudeBackend()
    windows = await backend.get_usage(b"oauth-token-123", isolation_dir=tmp_path)
    assert len(windows) == 1
    assert windows[0].window_type == "five_hour"
    assert windows[0].usage_percent == 42.5


@pytest.mark.asyncio
async def test_claude_usage_with_api_key_returns_empty(tmp_path):
    backend = ClaudeBackend()
    windows = await backend.get_usage(b"sk-ant-abc123", isolation_dir=tmp_path)
    assert windows == []


@pytest.mark.asyncio
async def test_claude_usage_api_error_returns_empty(tmp_path, httpx_mock):
    httpx_mock.add_response(url="https://api.anthropic.com/api/oauth/usage", status_code=403)
    backend = ClaudeBackend()
    windows = await backend.get_usage(b"oauth-token-123", isolation_dir=tmp_path)
    assert windows == []
