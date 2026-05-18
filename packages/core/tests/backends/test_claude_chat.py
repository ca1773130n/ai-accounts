from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from ai_accounts_core.backends.claude import ClaudeBackend
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
async def test_claude_chat_streams_tokens(tmp_path, httpx_mock):
    sse = _sse(
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}\n\n',
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}\n\n',
    )
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = ClaudeBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="claude-sonnet-4-20250514"),
        b"sk-ant-test",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert any(e.kind == "token" and e.payload == "Hi" for e in events)
    assert any(e.kind == "done" for e in events)
    done_event = next(e for e in events if e.kind == "done")
    assert done_event.payload["finish_reason"] == "end_turn"
    assert done_event.payload["tokens_out"] == 5


@pytest.mark.asyncio
async def test_claude_chat_system_message(tmp_path, httpx_mock):
    sse = _sse(
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"OK"}}\n\n',
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n',
    )
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = ClaudeBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(
            messages=(_msg("system", "You are helpful"), _msg("user", "Hi")),
            model="claude-sonnet-4-20250514",
        ),
        b"sk-ant-test",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    # Verify the request body had system field set and system msg excluded from messages
    req = httpx_mock.get_requests()[0]
    body = json.loads(req.content)
    assert body["system"] == "You are helpful"
    assert all(m["role"] != "system" for m in body["messages"])


@pytest.mark.asyncio
async def test_claude_chat_api_error(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=401,
        content=b"Unauthorized",
    )
    backend = ClaudeBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="claude-sonnet-4-20250514"),
        b"bad-key",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "401" in str(events[0].payload)
