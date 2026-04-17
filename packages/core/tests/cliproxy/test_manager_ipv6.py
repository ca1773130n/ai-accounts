"""Tests for IPv6 loopback + IPv4 fallback in forward_cliproxy_callback.

Claude CLI v2.1.92+ binds its local OAuth callback server to ``[::1]`` on
macOS with an IPv6-first stack. The forwarder must try IPv6 first and fall
back to IPv4 so it works regardless of which family the child CLI chose.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from ai_accounts_core.cliproxy.manager import forward_cliproxy_callback


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


async def test_forward_callback_tries_ipv6_first():
    """The first host attempted is ``[::1]`` — if it succeeds, IPv4 is not tried."""
    calls: list[str] = []

    async def fake_get(self, url: str, *, params=None):
        calls.append(url)
        return _FakeResponse(200)

    with patch.object(httpx.AsyncClient, "get", new=fake_get):
        result = await forward_cliproxy_callback(
            "http://localhost:54545/callback?code=abc&state=xyz"
        )

    assert result["status"] == "completed"
    assert calls, "expected at least one httpx call"
    assert calls[0].startswith("http://[::1]:"), (
        f"expected IPv6 host to be tried first, got {calls[0]!r}"
    )
    # Must not have tried IPv4 because IPv6 returned success.
    assert len(calls) == 1, f"expected single call on IPv6 success, got {calls}"


async def test_forward_callback_falls_back_to_ipv4_on_ipv6_failure():
    """If IPv6 connect fails, IPv4 (127.0.0.1 then localhost) is attempted."""
    calls: list[str] = []

    async def fake_get(self, url: str, *, params=None):
        calls.append(url)
        if url.startswith("http://[::1]"):
            raise httpx.ConnectError("no IPv6 listener")
        return _FakeResponse(200)

    with patch.object(httpx.AsyncClient, "get", new=fake_get):
        result = await forward_cliproxy_callback(
            "http://localhost:54545/callback?code=abc&state=xyz"
        )

    assert result["status"] == "completed"
    assert any(c.startswith("http://[::1]:") for c in calls)
    assert any(c.startswith("http://127.0.0.1:") for c in calls)


async def test_forward_callback_reports_error_when_all_hosts_fail():
    """If every host raises, we return a single aggregated error."""
    async def fake_get(self, url: str, *, params=None):
        raise httpx.ConnectError("refused")

    with patch.object(httpx.AsyncClient, "get", new=fake_get):
        result = await forward_cliproxy_callback(
            "http://localhost:54545/callback?code=abc&state=xyz"
        )

    assert result["status"] == "error"
    assert "reach" in result["message"].lower() or "refused" in result["message"].lower()


async def test_forward_callback_surfaces_last_http_status():
    """If every host answers with an HTTP error, the last status is reported."""
    async def fake_get(self, url: str, *, params=None):
        return _FakeResponse(500)

    with patch.object(httpx.AsyncClient, "get", new=fake_get):
        result = await forward_cliproxy_callback(
            "http://localhost:54545/callback?code=abc&state=xyz"
        )

    assert result["status"] == "error"
    assert "500" in result["message"]
