from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ai_accounts_core.backends.openai_compat import OpenAiCompatBackend
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.login.events import (
    LoginComplete,
    PromptAnswer,
    TextPrompt,
)
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent

_BASE_URL = "https://example.test/custom/v1"


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


def _credential(base_url: str = _BASE_URL, api_key: str = "sk-test-key") -> bytes:
    return json.dumps({"api_key": api_key, "base_url": base_url}).encode()


async def _drain(session) -> list:
    return [evt async for evt in session.events()]


@pytest.mark.asyncio
async def test_login_round_trips_base_url(tmp_path: Path):
    """The two-step api_key flow yields base_url then api_key prompts and
    stores both in JSON credential bytes."""
    backend = OpenAiCompatBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="base_url", answer=_BASE_URL))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-roundtrip"))
    events = await events_task

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert [p.prompt_id for p in text_prompts] == ["base_url", "api_key"]
    assert len(completes) == 1

    assert session.credential is not None
    decoded = json.loads(session.credential.decode())
    assert decoded == {"api_key": "sk-roundtrip", "base_url": _BASE_URL}


@pytest.mark.asyncio
async def test_chat_posts_to_configured_base_url(tmp_path: Path, httpx_mock):
    """chat() must POST to {base_url}/chat/completions — NOT a hardcoded host."""
    sse = _sse(
        'data: {"id":"gen-1","choices":[{"index":0,"delta":{"content":"Hey"},"finish_reason":null}]}\n\n',
        'data: {"id":"gen-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"model":"qwen-max"}\n\n',
        "data: [DONE]\n\n",
    )
    httpx_mock.add_response(
        url=f"{_BASE_URL}/chat/completions",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = OpenAiCompatBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hey"),), model="qwen-max"),
        _credential(),
        isolation_dir=tmp_path,
    ):
        events.append(e)

    assert any(e.kind == "token" and e.payload == "Hey" for e in events)
    assert any(e.kind == "done" for e in events)

    req = httpx_mock.get_requests()[0]
    assert str(req.url) == f"{_BASE_URL}/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-test-key"


@pytest.mark.asyncio
async def test_chat_empty_base_url_errors(tmp_path: Path):
    backend = OpenAiCompatBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="qwen-max"),
        b"",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert len(events) == 1
    assert events[0].kind == "error"


@pytest.mark.asyncio
async def test_chat_api_error(tmp_path: Path, httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE_URL}/chat/completions",
        method="POST",
        status_code=500,
        content=b"Internal Server Error",
    )
    backend = OpenAiCompatBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="qwen-max"),
        _credential(),
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "500" in str(events[0].payload)


@pytest.mark.asyncio
async def test_validate_hits_configured_base_url(tmp_path: Path, httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE_URL}/models",
        method="GET",
        json={"data": [{"id": "qwen-max"}]},
    )
    backend = OpenAiCompatBackend()
    ok = await backend.validate(_credential(), isolation_dir=tmp_path)
    assert ok is True
    req = httpx_mock.get_requests()[0]
    assert str(req.url) == f"{_BASE_URL}/models"


@pytest.mark.asyncio
async def test_validate_empty_credential_false(tmp_path: Path):
    backend = OpenAiCompatBackend()
    assert await backend.validate(b"", isolation_dir=tmp_path) is False
    assert await backend.validate(b"not json", isolation_dir=tmp_path) is False


@pytest.mark.asyncio
async def test_list_models_falls_back_on_empty_base_url(tmp_path: Path):
    backend = OpenAiCompatBackend()
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    assert models == []  # static fallback for openai_compat is empty


@pytest.mark.asyncio
async def test_detect_keyless_available():
    backend = OpenAiCompatBackend()
    result = await backend.detect()
    assert result.installed is True


@pytest.mark.asyncio
async def test_get_usage_empty(tmp_path: Path):
    backend = OpenAiCompatBackend()
    assert await backend.get_usage(_credential(), isolation_dir=tmp_path) == []
