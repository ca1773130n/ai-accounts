"""Unit tests for _chat_via_cliproxy error message extraction.

The interesting contract is the non-200 path: we want the user to see the
upstream cause ("unknown provider for model X", quota exhausted, …)
instead of the bare "Proxy error 502" we used to emit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from unittest.mock import patch

import pytest
from ai_accounts_core.backends._cliproxy_chat import _chat_via_cliproxy
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.protocols.backend import ChatRequest


def _msg(role: str, content: str) -> ChatMessage:
    return ChatMessage(
        id="msg-1",
        session_id="sess-1",
        role=ChatRole(role),
        content=content,
        created_at=datetime.now(),
    )


class _FakeStreamResp:
    """Async-context-manager mimicking httpx.AsyncClient.stream(...)."""

    def __init__(self, status_code: int, body: bytes, headers: dict | None = None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self) -> AsyncIterator[str]:
        # Should never be called on the error path — produce nothing.
        if False:
            yield ""


def _patch_cliproxy_returning(status_code: int, body: bytes, headers: dict | None = None):
    """Patch detect_cliproxy + httpx.AsyncClient.stream so the next chat
    call sees a `status_code` response with the given body."""

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def stream(self, *a, **kw):
            return _FakeStreamResp(status_code, body, headers)

    # detect_cliproxy is imported lazily inside _chat_via_cliproxy via
    # `from ai_accounts_core.cliproxy import detect_cliproxy` — patch at the
    # source module, not the consumer.
    return [
        patch(
            "ai_accounts_core.cliproxy.detect_cliproxy",
            return_value=("http://127.0.0.1:8317/v1", "not-needed"),
        ),
        patch(
            "ai_accounts_core.backends._cliproxy_chat.httpx.AsyncClient",
            _FakeClient,
        ),
    ]


async def _collect(req: ChatRequest) -> list:
    events = []
    async for ev in _chat_via_cliproxy(req):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_openai_style_json_error_message_is_surfaced():
    body = b'{"error":{"message":"unknown provider for model gpt-9000","type":"server_error","code":"internal_server_error"}}'
    patches = _patch_cliproxy_returning(502, body)
    req = ChatRequest(messages=(_msg("user", "hi"),), model="gpt-9000")
    for p in patches:
        p.start()
    try:
        events = await _collect(req)
    finally:
        for p in patches:
            p.stop()
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "error"
    assert "Proxy error 502" in ev.payload
    assert "unknown provider for model gpt-9000" in ev.payload


@pytest.mark.asyncio
async def test_openai_style_json_error_with_only_code():
    """Some upstream errors only have `code`, no `message`."""
    body = b'{"error":{"code":"rate_limited"}}'
    patches = _patch_cliproxy_returning(429, body)
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x")
    for p in patches:
        p.start()
    try:
        events = await _collect(req)
    finally:
        for p in patches:
            p.stop()
    assert events[0].payload == "Proxy error 429: rate_limited"


@pytest.mark.asyncio
async def test_plain_text_body_falls_back_to_excerpt():
    """Non-JSON body — should still surface a sanitized excerpt, not just the code."""
    body = b"upstream  unavailable\n\nlogs:\nfailed to connect"
    patches = _patch_cliproxy_returning(503, body)
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x")
    for p in patches:
        p.start()
    try:
        events = await _collect(req)
    finally:
        for p in patches:
            p.stop()
    assert events[0].kind == "error"
    # Whitespace runs collapsed, so multi-line is folded.
    assert "Proxy error 503" in events[0].payload
    assert "upstream unavailable" in events[0].payload
    assert "failed to connect" in events[0].payload


@pytest.mark.asyncio
async def test_empty_body_yields_bare_status_message():
    """Empty body shouldn't crash the parser — fall back to bare 'Proxy error N'."""
    patches = _patch_cliproxy_returning(500, b"")
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x")
    for p in patches:
        p.start()
    try:
        events = await _collect(req)
    finally:
        for p in patches:
            p.stop()
    # An empty body has no detail to surface — payload is the bare message.
    assert events[0].payload == "Proxy error 500"


@pytest.mark.asyncio
async def test_malformed_json_falls_back_to_excerpt():
    """Looks-like-JSON but isn't — fall back to text excerpt rather than raising."""
    body = b'{"error":  not actually json'
    patches = _patch_cliproxy_returning(500, body)
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x")
    for p in patches:
        p.start()
    try:
        events = await _collect(req)
    finally:
        for p in patches:
            p.stop()
    assert events[0].kind == "error"
    # Excerpt of the body is included — the literal text shows up.
    assert "Proxy error 500" in events[0].payload
    assert "not actually json" in events[0].payload


@pytest.mark.asyncio
async def test_gzipped_error_body_is_decompressed():
    """When the upstream sends Content-Encoding: gzip, httpx streaming
    mode returns raw compressed bytes — and we used to render them as
    garbage in the UI. Verify decompression."""
    import gzip

    plaintext = b'{"error":{"message":"upstream rate limit exceeded"}}'
    body = gzip.compress(plaintext)
    patches = _patch_cliproxy_returning(429, body, {"content-encoding": "gzip"})
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x")
    for p in patches:
        p.start()
    try:
        events = await _collect(req)
    finally:
        for p in patches:
            p.stop()
    assert events[0].kind == "error"
    assert "Proxy error 429" in events[0].payload
    assert "upstream rate limit exceeded" in events[0].payload


@pytest.mark.asyncio
async def test_gzipped_body_without_header_decoded_via_magic_bytes():
    """Server forgot the Content-Encoding header but body is still gzip.
    Heuristic falls back to gzip-magic-byte detection."""
    import gzip

    plaintext = b'{"error":{"message":"oops"}}'
    body = gzip.compress(plaintext)
    patches = _patch_cliproxy_returning(500, body, {})  # no header
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x")
    for p in patches:
        p.start()
    try:
        events = await _collect(req)
    finally:
        for p in patches:
            p.stop()
    assert events[0].kind == "error"
    assert "oops" in events[0].payload
