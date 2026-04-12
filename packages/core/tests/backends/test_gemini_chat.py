from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

from ai_accounts_core.backends.gemini import GeminiBackend
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


_GEMINI_URL_RE = re.compile(
    r"https://generativelanguage\.googleapis\.com/v1beta/models/.+:streamGenerateContent.*"
)


@pytest.mark.asyncio
async def test_gemini_chat_streams_tokens(tmp_path, httpx_mock):
    sse = _sse(
        'data: {"candidates":[{"content":{"parts":[{"text":"Hi there"}],"role":"model"},"finishReason":null}]}\n\n',
        'data: {"candidates":[{"content":{"parts":[{"text":""}],"role":"model"},"finishReason":"STOP"}]}\n\n',
    )
    httpx_mock.add_response(
        url=_GEMINI_URL_RE,
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = GeminiBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hello"),), model="gemini-2.0-flash"),
        b"AIzaSy-test-key",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert any(e.kind == "token" and e.payload == "Hi there" for e in events)
    assert any(e.kind == "done" for e in events)
    done_event = next(e for e in events if e.kind == "done")
    assert done_event.payload["finish_reason"] == "STOP"


@pytest.mark.asyncio
async def test_gemini_chat_role_mapping(tmp_path, httpx_mock):
    sse = _sse(
        'data: {"candidates":[{"content":{"parts":[{"text":"OK"}],"role":"model"},"finishReason":"STOP"}]}\n\n',
    )
    httpx_mock.add_response(
        url=_GEMINI_URL_RE,
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = GeminiBackend()
    async for _ in backend.chat(
        ChatRequest(
            messages=(
                _msg("system", "Be helpful"),
                _msg("user", "Hi"),
                _msg("assistant", "Hello"),
                _msg("user", "Thanks"),
            ),
            model="gemini-2.0-flash",
        ),
        b"AIzaSy-test-key",
        isolation_dir=tmp_path,
    ):
        pass
    req = httpx_mock.get_requests()[0]
    body = json.loads(req.content)
    # System message goes to system_instruction, not contents
    assert "system_instruction" in body
    roles = [c["role"] for c in body["contents"]]
    assert roles == ["user", "model", "user"]


@pytest.mark.asyncio
async def test_gemini_chat_api_error(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url=_GEMINI_URL_RE,
        method="POST",
        status_code=403,
        content=b"Forbidden",
    )
    backend = GeminiBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="gemini-2.0-flash"),
        b"bad-key",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "403" in str(events[0].payload)
