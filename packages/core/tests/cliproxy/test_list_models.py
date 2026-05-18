"""Unit tests for cliproxy_list_models — the live model discovery helper.

Tests are designed to run regardless of whether a real cliproxyapi happens to
be running on the dev machine — every test patches `detect_cliproxy` and the
httpx call so the assertions are deterministic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from ai_accounts_core.cliproxy.manager import cliproxy_list_models


def _fake_models_response(items: list[dict]):
    """Build a stand-in for an httpx Response with a `data` array."""
    fake = AsyncMock()
    fake.status_code = 200
    fake.json = lambda: {"data": items}
    return fake


def _fake_async_client(get_returns):
    """Patch httpx.AsyncClient so .get(...) returns `get_returns` (or raises if exc)."""

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **kw):
            if isinstance(get_returns, BaseException):
                raise get_returns
            return get_returns

    return patch("ai_accounts_core.cliproxy.manager.httpx.AsyncClient", _FakeClient)


@pytest.fixture
def proxy_up():
    """detect_cliproxy returns a base_url + api_key."""
    return patch(
        "ai_accounts_core.cliproxy.manager.detect_cliproxy",
        return_value=("http://127.0.0.1:8317/v1", "not-needed"),
    )


@pytest.fixture
def proxy_down():
    """detect_cliproxy returns None — proxy not running."""
    return patch(
        "ai_accounts_core.cliproxy.manager.detect_cliproxy",
        return_value=None,
    )


@pytest.mark.asyncio
async def test_returns_none_for_unmapped_kind():
    """opencode is not in _CLIPROXY_OWNED_BY → never even probes the proxy."""
    with patch("ai_accounts_core.cliproxy.manager.detect_cliproxy") as detect_mock:
        result = await cliproxy_list_models("opencode")
    assert result is None
    # Should not have probed the proxy at all (early return on unmapped kind).
    detect_mock.assert_not_called()


@pytest.mark.asyncio
async def test_returns_none_when_proxy_unreachable(proxy_down):
    with proxy_down:
        assert await cliproxy_list_models("claude") is None
        assert await cliproxy_list_models("codex") is None
        assert await cliproxy_list_models("gemini") is None


@pytest.mark.asyncio
async def test_returns_none_on_non_200_status(proxy_up):
    """5xx / 4xx from /v1/models → None (caller falls back to static)."""
    fake_resp = AsyncMock()
    fake_resp.status_code = 500
    fake_resp.json = lambda: {"error": "boom"}
    with proxy_up, _fake_async_client(fake_resp):
        result = await cliproxy_list_models("claude")
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_httpx_exception(proxy_up):
    """Network error mid-request → None (don't crash the chat panel)."""
    with proxy_up, _fake_async_client(httpx.ConnectError("refused")):
        assert await cliproxy_list_models("claude") is None


@pytest.mark.asyncio
async def test_returns_none_on_malformed_body(proxy_up):
    """If `data` isn't a list (or missing entirely), bail to None."""
    fake = AsyncMock()
    fake.status_code = 200
    fake.json = lambda: {"data": "not a list"}
    with proxy_up, _fake_async_client(fake):
        assert await cliproxy_list_models("claude") is None

    fake.json = lambda: {}  # no data key at all
    with proxy_up, _fake_async_client(fake):
        assert await cliproxy_list_models("claude") is None


@pytest.mark.asyncio
async def test_filters_by_owned_by(proxy_up):
    """Mixed owned_by → only the kind's matches come back."""
    items = [
        {"id": "claude-opus-4-6", "owned_by": "anthropic"},
        {"id": "claude-sonnet-4-6", "owned_by": "anthropic"},
        {"id": "gpt-5-codex", "owned_by": "openai"},
        {"id": "gpt-5", "owned_by": "openai"},
        {"id": "gemini-2.5-pro", "owned_by": "google"},
        {"id": "some-other", "owned_by": "huggingface"},
    ]
    with proxy_up, _fake_async_client(_fake_models_response(items)):
        claude = await cliproxy_list_models("claude")
        codex = await cliproxy_list_models("codex")
        gemini = await cliproxy_list_models("gemini")

    assert [m["id"] for m in claude] == ["claude-opus-4-6", "claude-sonnet-4-6"]
    assert [m["id"] for m in codex] == ["gpt-5-codex", "gpt-5"]
    assert [m["id"] for m in gemini] == ["gemini-2.5-pro"]


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_matches(proxy_up):
    """Cliproxy reachable but advertises zero models for this kind → []
    (NOT None — distinguishes 'cliproxy says no' from 'cliproxy unreachable')."""
    items = [{"id": "gemini-2.5-pro", "owned_by": "google"}]
    with proxy_up, _fake_async_client(_fake_models_response(items)):
        result = await cliproxy_list_models("claude")
    assert result == []  # crucial: empty list, not None


@pytest.mark.asyncio
async def test_skips_items_missing_id(proxy_up):
    """Defensive: an item without `id` (malformed cliproxy response) is dropped."""
    items = [
        {"id": "claude-opus-4-6", "owned_by": "anthropic"},
        {"owned_by": "anthropic"},  # missing id
        {"id": None, "owned_by": "anthropic"},  # null id
    ]
    with proxy_up, _fake_async_client(_fake_models_response(items)):
        result = await cliproxy_list_models("claude")
    assert [m["id"] for m in result] == ["claude-opus-4-6"]


@pytest.mark.asyncio
async def test_skips_non_dict_items(proxy_up):
    """Defensive: stray strings/None in the data array don't crash the filter."""
    items = [
        {"id": "claude-opus-4-6", "owned_by": "anthropic"},
        "claude-haiku-bad-shape",
        None,
        42,
    ]
    with proxy_up, _fake_async_client(_fake_models_response(items)):
        result = await cliproxy_list_models("claude")
    assert [m["id"] for m in result] == ["claude-opus-4-6"]
