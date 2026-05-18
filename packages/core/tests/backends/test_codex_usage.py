from __future__ import annotations

import pytest
from ai_accounts_core.backends.codex import CodexBackend


@pytest.mark.asyncio
async def test_codex_usage_with_token(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://chatgpt.com/backend-api/wham/usage",
        json={
            "rate_limits": [
                {
                    "primary_window": {
                        "used_percent": 60.0,
                        "reset_at": 1744495200,
                    },
                    "secondary_window": {
                        "used_percent": 10.0,
                    },
                }
            ]
        },
    )
    backend = CodexBackend()
    windows = await backend.get_usage(b"some-token", isolation_dir=tmp_path)
    assert len(windows) == 2
    assert windows[0].window_type == "primary_window"
    assert windows[0].usage_percent == 60.0
    assert windows[0].resets_at is not None
    assert windows[1].window_type == "secondary_window"
    assert windows[1].usage_percent == 10.0
    assert windows[1].resets_at is None


@pytest.mark.asyncio
async def test_codex_usage_api_error_returns_empty(tmp_path, httpx_mock):
    httpx_mock.add_response(url="https://chatgpt.com/backend-api/wham/usage", status_code=500)
    backend = CodexBackend()
    windows = await backend.get_usage(b"some-token", isolation_dir=tmp_path)
    assert windows == []
