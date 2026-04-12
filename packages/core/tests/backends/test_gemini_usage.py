from __future__ import annotations

import pytest

from ai_accounts_core.backends.gemini import GeminiBackend
from ai_accounts_core.domain.usage import UsageWindow


@pytest.mark.asyncio
async def test_gemini_usage_with_token(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
        json={
            "buckets": [
                {
                    "modelId": "gemini-2.5-pro",
                    "remainingFraction": 0.75,
                    "resetTime": "2026-04-12T20:00:00+00:00",
                }
            ]
        },
    )
    backend = GeminiBackend()
    windows = await backend.get_usage(b"ya29.token", isolation_dir=tmp_path)
    assert len(windows) == 1
    assert windows[0].window_type == "gemini-2.5-pro"
    assert windows[0].usage_percent == pytest.approx(25.0)
    assert windows[0].resets_at is not None


@pytest.mark.asyncio
async def test_gemini_usage_api_error_returns_empty(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
        status_code=401,
    )
    backend = GeminiBackend()
    windows = await backend.get_usage(b"ya29.token", isolation_dir=tmp_path)
    assert windows == []
