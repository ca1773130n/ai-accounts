from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ai_accounts_core.backends.opencode import OpenCodeBackend
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent


def _msg(role: str, content: str) -> ChatMessage:
    return ChatMessage(
        id="m1",
        session_id="s1",
        role=ChatRole(role),
        content=content,
        created_at=datetime.now(UTC),
    )


def _sse(*events: str) -> bytes:
    return "".join(events).encode()


@pytest.mark.asyncio
async def test_opencode_chat_streams_tokens(tmp_path, httpx_mock):
    sse = _sse(
        'data: {"id":"gen-1","choices":[{"index":0,"delta":{"content":"Hey"},"finish_reason":null}]}\n\n',
        'data: {"id":"gen-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"model":"openai/gpt-4o"}\n\n',
        "data: [DONE]\n\n",
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = OpenCodeBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hey"),), model="openai/gpt-4o"),
        b"sk-or-test-key",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert any(e.kind == "token" and e.payload == "Hey" for e in events)
    assert any(e.kind == "done" for e in events)
    done_event = next(e for e in events if e.kind == "done")
    assert done_event.payload["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_opencode_chat_uses_openrouter_url(tmp_path, httpx_mock):
    sse = _sse(
        'data: {"id":"gen-1","choices":[{"index":0,"delta":{"content":"x"},"finish_reason":"stop"}],"model":"openai/gpt-4o"}\n\n',
        "data: [DONE]\n\n",
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = OpenCodeBackend()
    async for _ in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="openai/gpt-4o"),
        b"sk-or-test-key",
        isolation_dir=tmp_path,
    ):
        pass
    req = httpx_mock.get_requests()[0]
    assert "openrouter.ai" in str(req.url)
    assert req.headers["authorization"] == "Bearer sk-or-test-key"


@pytest.mark.asyncio
async def test_opencode_chat_api_error(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        status_code=500,
        content=b"Internal Server Error",
    )
    backend = OpenCodeBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="openai/gpt-4o"),
        b"sk-or-test-key",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "500" in str(events[0].payload)
