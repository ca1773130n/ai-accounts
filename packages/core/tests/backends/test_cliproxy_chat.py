"""Unit tests for _chat_via_cliproxy error message extraction and function
calling.

The interesting contracts are (a) the non-200 path: we want the user to see
the upstream cause ("unknown provider for model X", quota exhausted, …)
instead of the bare "Proxy error 502" we used to emit; and (b) tool calls,
which ride in on `params["tools"]` and come back as `tool_call` events
accumulated from the fragments OpenAI streams.
"""

from __future__ import annotations

import json
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


# --- function calling -------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_nodes",
            "description": "Search the knowledge graph",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    }
]


class _FakeStreamingResp(_FakeStreamResp):
    """200 response that replays a list of SSE lines."""

    def __init__(self, lines: list[str]):
        super().__init__(200, b"")
        self._lines = lines

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


def _patch_cliproxy_streaming(lines: list[str], sent: dict):
    """Patch the proxy so the next chat call streams `lines`, recording the
    POST body into `sent` so the request side can be asserted too."""

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def stream(self, *a, **kw):
            sent.update(kw.get("json") or {})
            return _FakeStreamingResp(lines)

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


async def _collect_streaming(req: ChatRequest, lines: list[str]) -> tuple[list, dict]:
    sent: dict = {}
    patches = _patch_cliproxy_streaming(lines, sent)
    for p in patches:
        p.start()
    try:
        return await _collect(req), sent
    finally:
        for p in patches:
            p.stop()


def _tool_delta(index: int, *, call_id: str | None = None, **function) -> str:
    """One SSE line carrying a single tool-call fragment, OpenAI-shaped."""
    call: dict = {"index": index, "function": function}
    if call_id is not None:
        call["id"] = call_id
    return "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [call]}}]})


@pytest.mark.asyncio
async def test_tools_are_copied_into_the_request_body():
    req = ChatRequest(
        messages=(_msg("user", "hi"),),
        model="x",
        params={"tools": TOOLS, "tool_choice": "auto"},
    )
    _, sent = await _collect_streaming(req, ["data: [DONE]"])
    assert sent["tools"] == TOOLS
    assert sent["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_no_tools_key_at_all_when_none_requested():
    """`tools: []` is not the same as no tools to some servers."""
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x")
    _, sent = await _collect_streaming(req, ["data: [DONE]"])
    assert "tools" not in sent
    assert "tool_choice" not in sent
    assert sent["model"] == "x"
    assert sent["stream"] is True


@pytest.mark.asyncio
async def test_empty_tools_list_is_omitted():
    req = ChatRequest(
        messages=(_msg("user", "hi"),), model="x", params={"tools": [], "tool_choice": "auto"}
    )
    _, sent = await _collect_streaming(req, ["data: [DONE]"])
    assert "tools" not in sent
    assert "tool_choice" not in sent


@pytest.mark.asyncio
async def test_tool_call_split_across_deltas_emits_one_event():
    lines = [
        _tool_delta(0, call_id="call_1", name="search_nodes", arguments=""),
        _tool_delta(0, arguments='{"q": "diff'),
        _tool_delta(0, arguments='usion"}'),
        "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]",
    ]
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x", params={"tools": TOOLS})
    events, _ = await _collect_streaming(req, lines)
    calls = [e for e in events if e.kind == "tool_call"]
    assert len(calls) == 1
    assert calls[0].payload == {
        "id": "call_1",
        "name": "search_nodes",
        "arguments": '{"q": "diffusion"}',
    }
    # Emitted before `done`, since consumers may stop reading at done.
    assert [e.kind for e in events] == ["tool_call", "done"]


@pytest.mark.asyncio
async def test_parallel_tool_calls_emit_one_event_each_in_index_order():
    lines = [
        _tool_delta(0, call_id="call_a", name="timeline", arguments='{"t":'),
        _tool_delta(1, call_id="call_b", name="compare_methods", arguments='{"m":'),
        _tool_delta(1, arguments='"x"}'),
        _tool_delta(0, arguments='"y"}'),
        "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
    ]
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x", params={"tools": TOOLS})
    events, _ = await _collect_streaming(req, lines)
    calls = [e for e in events if e.kind == "tool_call"]
    assert [c.payload["name"] for c in calls] == ["timeline", "compare_methods"]
    assert [c.payload["arguments"] for c in calls] == ['{"t":"y"}', '{"m":"x"}']


@pytest.mark.asyncio
async def test_tool_call_without_finish_reason_is_still_emitted():
    """A proxy that ends the stream at [DONE] must not swallow the call."""
    lines = [
        _tool_delta(0, call_id="call_1", name="timeline", arguments="{}"),
        "data: [DONE]",
    ]
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x", params={"tools": TOOLS})
    events, _ = await _collect_streaming(req, lines)
    assert [e.kind for e in events] == ["tool_call"]
    assert events[0].payload["arguments"] == "{}"


@pytest.mark.asyncio
async def test_plain_token_stream_is_unchanged():
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "Hel"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "lo"}}]}),
        "data: "
        + json.dumps(
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2},
            }
        ),
        "data: [DONE]",
    ]
    req = ChatRequest(messages=(_msg("user", "hi"),), model="x")
    events, _ = await _collect_streaming(req, lines)
    assert [e.kind for e in events] == ["token", "token", "done"]
    assert "".join(e.payload for e in events[:2]) == "Hello"
    assert events[2].payload == {
        "finish_reason": "stop",
        "tokens_in": 7,
        "tokens_out": 2,
        "model": "x",
    }
