from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ai_accounts_core.backends.deepseek import DeepSeekBackend
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


def test_deepseek_metadata_and_login_flow():
    backend = DeepSeekBackend()
    assert backend.kind == "deepseek"
    assert backend.metadata.display_name == "DeepSeek"
    assert backend.supported_login_flows == frozenset({"api_key"})
    session = backend.begin_login("api_key", {}, {}, __import__("pathlib").Path("."))
    assert session.flow_kind == "api_key"
    assert session.backend_kind == "deepseek"


@pytest.mark.asyncio
async def test_deepseek_validate_true_on_200(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/models",
        method="GET",
        status_code=200,
        json={"object": "list", "data": []},
    )
    assert await DeepSeekBackend().validate(b"sk-deepseek-test", isolation_dir=tmp_path) is True


@pytest.mark.asyncio
async def test_deepseek_validate_false_on_401(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/models",
        method="GET",
        status_code=401,
        json={"error": "unauthorized"},
    )
    assert await DeepSeekBackend().validate(b"sk-bad-key", isolation_dir=tmp_path) is False


@pytest.mark.asyncio
async def test_deepseek_validate_false_on_empty_key(tmp_path):
    assert await DeepSeekBackend().validate(b"", isolation_dir=tmp_path) is False


@pytest.mark.asyncio
async def test_deepseek_list_models_parses_data(tmp_path, httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/models",
        method="GET",
        status_code=200,
        json={"object": "list", "data": [{"id": "deepseek-v4-pro", "owned_by": "deepseek"}]},
    )
    models = await DeepSeekBackend().list_models(b"sk-deepseek-test", isolation_dir=tmp_path)
    assert any(m.id == "deepseek-v4-pro" for m in models)


@pytest.mark.asyncio
async def test_deepseek_chat_streams_tokens(tmp_path, httpx_mock):
    sse = _sse(
        'data: {"id":"gen-1","choices":[{"index":0,"delta":{"content":"Hey"},"finish_reason":null}]}\n\n',
        'data: {"id":"gen-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"model":"deepseek-v4-pro"}\n\n',
        "data: [DONE]\n\n",
    )
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = DeepSeekBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hey"),), model="deepseek-v4-pro"),
        b"sk-deepseek-test",
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert any(e.kind == "token" and e.payload == "Hey" for e in events)
    assert any(e.kind == "done" for e in events)


@pytest.mark.asyncio
async def test_deepseek_chat_posts_with_bearer(tmp_path, httpx_mock):
    sse = _sse(
        'data: {"id":"gen-1","choices":[{"index":0,"delta":{"content":"x"},"finish_reason":"stop"}],"model":"deepseek-v4-pro"}\n\n',
        "data: [DONE]\n\n",
    )
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = DeepSeekBackend()
    async for _ in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="deepseek-v4-pro"),
        b"sk-deepseek-test",
        isolation_dir=tmp_path,
    ):
        pass
    req = httpx_mock.get_requests()[0]
    assert str(req.url) == "https://api.deepseek.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-deepseek-test"


@pytest.mark.asyncio
async def test_deepseek_detect_is_keyless():
    result = await DeepSeekBackend().detect()
    assert result.installed is True


@pytest.mark.asyncio
async def test_deepseek_get_usage_empty(tmp_path):
    assert await DeepSeekBackend().get_usage(b"sk-deepseek-test", isolation_dir=tmp_path) == []
