from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ai_accounts_core.backends.codex import CodexBackend
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
async def test_codex_chat_streams_tokens(tmp_path, httpx_mock):
    sse = _sse(
        'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n',
        'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"model":"gpt-4o"}\n\n',
        "data: [DONE]\n\n",
    )
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = CodexBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hello"),), model="gpt-4o"),
        b"sk-test-key",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert any(e.kind == "token" and e.payload == "Hello" for e in events)
    assert any(e.kind == "done" for e in events)
    done_event = next(e for e in events if e.kind == "done")
    assert done_event.payload["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_codex_chat_sends_correct_headers(tmp_path, httpx_mock):
    sse = _sse(
        'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"x"},"finish_reason":"stop"}],"model":"gpt-4o"}\n\n',
        "data: [DONE]\n\n",
    )
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = CodexBackend()
    async for _ in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="gpt-4o"),
        b"sk-test-key",
        isolation_dir=tmp_path,
    ):
        pass
    req = httpx_mock.get_requests()[0]
    assert req.headers["authorization"] == "Bearer sk-test-key"


@pytest.mark.asyncio
async def test_codex_chat_api_error(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        status_code=429,
        content=b"Rate limited",
    )
    backend = CodexBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="gpt-4o"),
        b"sk-test-key",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "429" in str(events[0].payload)
