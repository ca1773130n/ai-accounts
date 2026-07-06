from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ai_accounts_core.backends.claude_custom import ClaudeCustomBackend, _parse_models
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginFailed,
    MenuPrompt,
    PromptAnswer,
    TextPrompt,
)
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent

_BASE_URL = "https://llm.example.test"
_MODELS = [
    {"id": "claude-sonnet-5", "display_name": "Sonnet 5"},
    {"id": "my-tuned-model", "display_name": "my-tuned-model"},
]


def _msg(role: str, content: str) -> ChatMessage:
    return ChatMessage(
        id="m1",
        session_id="s1",
        role=ChatRole(role),
        content=content,
        created_at=datetime.now(UTC),
    )


def _credential(
    base_url: str = _BASE_URL,
    api_key: str = "sk-test-key",
    models: list[dict[str, str]] | None = None,
    config_path: str = "",
) -> bytes:
    return json.dumps(
        {
            "base_url": base_url,
            "api_key": api_key,
            "models": _MODELS if models is None else models,
            "config_path": config_path,
        }
    ).encode()


async def _drain(session) -> list:
    return [evt async for evt in session.events()]


@pytest.mark.asyncio
async def test_login_round_trips_endpoint_and_models(tmp_path: Path):
    """base_url → auth menu → api_key → models; everything chat needs — incl.
    the wizard-typed config_path — lands in the JSON credential."""
    backend = ClaudeCustomBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={"config_path": "~/.claude-custom-work"},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    # Trailing slash and /v1 suffix are normalized away.
    await session.respond(PromptAnswer(prompt_id="base_url", answer=f"{_BASE_URL}/v1/"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="auth_mode", answer="1"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-roundtrip"))
    await asyncio.sleep(0)
    await session.respond(
        PromptAnswer(prompt_id="models", answer="claude-sonnet-5=Sonnet 5, my-tuned-model")
    )
    events = await events_task

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    menus = [e for e in events if isinstance(e, MenuPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert [p.prompt_id for p in text_prompts] == ["base_url", "api_key", "models"]
    assert [m.prompt_id for m in menus] == ["auth_mode"]
    assert len(completes) == 1

    assert session.credential is not None
    decoded = json.loads(session.credential.decode())
    assert decoded == {
        "base_url": _BASE_URL,
        "api_key": "sk-roundtrip",
        "models": _MODELS,
        "config_path": "~/.claude-custom-work",
    }


@pytest.mark.asyncio
async def test_login_keyless_skips_key_prompt(tmp_path: Path):
    """Menu option 2 (keyless) must NOT emit an api_key TextPrompt — the
    bundled LoginStream can't submit a blank field — and stores an empty key."""
    backend = ClaudeCustomBackend()
    session = backend.begin_login(
        flow_kind="api_key", config={}, vault_ctx={}, isolation_dir=tmp_path
    )
    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="base_url", answer=_BASE_URL))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="auth_mode", answer="2"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="models", answer="local-model"))
    events = await events_task

    prompt_ids = [e.prompt_id for e in events if isinstance(e, TextPrompt)]
    assert prompt_ids == ["base_url", "models"]
    assert session.credential is not None
    decoded = json.loads(session.credential.decode())
    assert decoded["api_key"] == ""
    assert decoded["models"] == [{"id": "local-model", "display_name": "local-model"}]


@pytest.mark.asyncio
async def test_login_rejects_unschemed_base_url(tmp_path: Path):
    backend = ClaudeCustomBackend()
    session = backend.begin_login(
        flow_kind="api_key", config={}, vault_ctx={}, isolation_dir=tmp_path
    )
    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="base_url", answer="llm.example.test"))
    events = await events_task
    failures = [e for e in events if isinstance(e, LoginFailed)]
    assert [f.code for f in failures] == ["invalid_base_url"]
    assert session.credential is None


@pytest.mark.asyncio
async def test_login_rejects_empty_model_list(tmp_path: Path):
    backend = ClaudeCustomBackend()
    session = backend.begin_login(
        flow_kind="api_key", config={}, vault_ctx={}, isolation_dir=tmp_path
    )
    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="base_url", answer=_BASE_URL))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="auth_mode", answer="2"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="models", answer=" , "))
    events = await events_task
    failures = [e for e in events if isinstance(e, LoginFailed)]
    assert [f.code for f in failures] == ["invalid_models"]


@pytest.mark.asyncio
async def test_login_cancel_terminates_session(tmp_path: Path):
    """cancel() mid-flow must unblock the generator with LoginFailed(cancelled)
    — a regression here leaves the login SSE stream hanging for 300s."""
    backend = ClaudeCustomBackend()
    session = backend.begin_login(
        flow_kind="api_key", config={}, vault_ctx={}, isolation_dir=tmp_path
    )
    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.cancel()
    events = await asyncio.wait_for(events_task, timeout=5)
    failures = [e for e in events if isinstance(e, LoginFailed)]
    assert [f.code for f in failures] == ["cancelled"]
    assert session.done is True
    assert session.credential is None


def test_parse_models_shapes():
    assert _parse_models("a=Alpha, b\n c=Sea") == [
        {"id": "a", "display_name": "Alpha"},
        {"id": "b", "display_name": "b"},
        {"id": "c", "display_name": "Sea"},
    ]
    assert _parse_models("") == []


@pytest.mark.asyncio
async def test_chat_posts_anthropic_shape_to_configured_base_url(tmp_path: Path, httpx_mock):
    """chat() must POST to {base_url}/v1/messages with the Anthropic SSE shape,
    lift the system message into body.system, and send both auth headers."""
    sse = (
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hey"}}\n\n'
        b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}\n\n'
    )
    httpx_mock.add_response(
        url=f"{_BASE_URL}/v1/messages",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = ClaudeCustomBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(
            messages=(_msg("system", "be brief"), _msg("user", "Hey")),
            model="claude-sonnet-5",
        ),
        _credential(),
        isolation_dir=tmp_path,
    ):
        events.append(e)

    assert any(e.kind == "token" and e.payload == "Hey" for e in events)
    done = [e for e in events if e.kind == "done"]
    assert done and done[0].payload["finish_reason"] == "end_turn"

    req = httpx_mock.get_requests()[0]
    assert str(req.url) == f"{_BASE_URL}/v1/messages"
    assert req.headers["x-api-key"] == "sk-test-key"
    assert req.headers["authorization"] == "Bearer sk-test-key"
    body = json.loads(req.content)
    assert body["system"] == "be brief"
    assert body["messages"] == [{"role": "user", "content": "Hey"}]
    assert body["max_tokens"] == 4096  # ChatService sends no params


@pytest.mark.asyncio
async def test_chat_keyless_sends_no_auth_headers(tmp_path: Path, httpx_mock):
    """A keyless account must not emit x-api-key / Authorization at all —
    strict gateways 401 on an empty bearer token."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/v1/messages",
        method="POST",
        content=b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{}}\n\n',
        headers={"content-type": "text/event-stream"},
    )
    backend = ClaudeCustomBackend()
    async for _ in backend.chat(
        ChatRequest(messages=(_msg("user", "Hey"),), model="local-model"),
        _credential(api_key=""),
        isolation_dir=tmp_path,
    ):
        pass
    header_names = {k.lower() for k in httpx_mock.get_requests()[0].headers}
    assert "x-api-key" not in header_names
    assert "authorization" not in header_names


@pytest.mark.asyncio
async def test_chat_stream_error_event_surfaces(tmp_path: Path, httpx_mock):
    """In-band {"type":"error"} SSE events (overloaded, gateway failure after
    HTTP 200) must yield an error event, not silently truncate the reply."""
    sse = (
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"partial"}}\n\n'
        b'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n\n'
    )
    httpx_mock.add_response(
        url=f"{_BASE_URL}/v1/messages",
        method="POST",
        content=sse,
        headers={"content-type": "text/event-stream"},
    )
    backend = ClaudeCustomBackend()
    events = [
        e
        async for e in backend.chat(
            ChatRequest(messages=(_msg("user", "Hey"),), model="m"),
            _credential(),
            isolation_dir=tmp_path,
        )
    ]
    assert [e.kind for e in events] == ["token", "error"]
    assert "Overloaded" in str(events[-1].payload)


@pytest.mark.asyncio
async def test_chat_empty_credential_errors(tmp_path: Path):
    backend = ClaudeCustomBackend()
    events = [
        e
        async for e in backend.chat(
            ChatRequest(messages=(_msg("user", "Hi"),), model="m"),
            b"",
            isolation_dir=tmp_path,
        )
    ]
    assert len(events) == 1
    assert events[0].kind == "error"


@pytest.mark.asyncio
async def test_chat_api_error(tmp_path: Path, httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE_URL}/v1/messages", method="POST", status_code=500, content=b"boom"
    )
    backend = ClaudeCustomBackend()
    events = [
        e
        async for e in backend.chat(
            ChatRequest(messages=(_msg("user", "Hi"),), model="m"),
            _credential(),
            isolation_dir=tmp_path,
        )
    ]
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "500" in str(events[0].payload)


@pytest.mark.asyncio
async def test_validate_models_endpoint_ok(tmp_path: Path, httpx_mock):
    httpx_mock.add_response(url=f"{_BASE_URL}/v1/models", method="GET", json={"data": []})
    backend = ClaudeCustomBackend()
    assert await backend.validate(_credential(), isolation_dir=tmp_path) is True


@pytest.mark.asyncio
async def test_validate_key_rejected_false(tmp_path: Path, httpx_mock):
    httpx_mock.add_response(url=f"{_BASE_URL}/v1/models", method="GET", status_code=401)
    backend = ClaudeCustomBackend()
    assert await backend.validate(_credential(), isolation_dir=tmp_path) is False


@pytest.mark.asyncio
async def test_validate_falls_back_to_messages_probe(tmp_path: Path, httpx_mock):
    """Gateways without /v1/models (404) fall back to a 1-token /v1/messages
    probe; a 400 there proves a reachable Anthropic-compatible route."""
    httpx_mock.add_response(url=f"{_BASE_URL}/v1/models", method="GET", status_code=404)
    httpx_mock.add_response(url=f"{_BASE_URL}/v1/messages", method="POST", status_code=400, json={})
    backend = ClaudeCustomBackend()
    cred = _credential(api_key="")
    assert await backend.validate(cred, isolation_dir=tmp_path) is True


@pytest.mark.asyncio
async def test_validate_empty_credential_false(tmp_path: Path):
    backend = ClaudeCustomBackend()
    assert await backend.validate(b"", isolation_dir=tmp_path) is False
    assert await backend.validate(b"not json", isolation_dir=tmp_path) is False


@pytest.mark.asyncio
async def test_list_models_returns_manual_list_in_order(tmp_path: Path):
    """No network call — the manual list, first entry first (it is the default
    model for the chat panel and all/compound modes)."""
    backend = ClaudeCustomBackend()
    models = await backend.list_models(_credential(), isolation_dir=tmp_path)
    assert [(m.id, m.display_name) for m in models] == [
        ("claude-sonnet-5", "Sonnet 5"),
        ("my-tuned-model", "my-tuned-model"),
    ]
    assert await backend.list_models(b"", isolation_dir=tmp_path) == []


@pytest.mark.asyncio
async def test_detect_no_cli_required():
    assert (await ClaudeCustomBackend().detect()).installed is True


@pytest.mark.asyncio
async def test_get_usage_empty(tmp_path: Path):
    assert await ClaudeCustomBackend().get_usage(_credential(), isolation_dir=tmp_path) == []


def test_pty_env_wires_endpoint_and_config_dir(tmp_path: Path, monkeypatch):
    """The claude CLI must see the self-hosted endpoint and the user's custom
    config dir (from the credential — backend.config never reaches pty), and
    an ambient AUTH_TOKEN must not override the account's key."""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ambient-real-token")
    backend = ClaudeCustomBackend()
    custom_dir = tmp_path / "custom-claude-home"
    env = backend._env(
        _credential(config_path=str(custom_dir)),
        tmp_path / "iso",
    )
    assert env["ANTHROPIC_BASE_URL"] == _BASE_URL
    assert env["ANTHROPIC_API_KEY"] == "sk-test-key"
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["ANTHROPIC_MODEL"] == "claude-sonnet-5"
    assert env["CLAUDE_CONFIG_DIR"] == str(custom_dir.resolve())
    assert custom_dir.is_dir()  # created on touch


def test_pty_env_keyless_strips_ambient_credentials(tmp_path: Path, monkeypatch):
    """A keyless account points the CLI at a third-party host — the operator's
    real Anthropic credentials must never ride along from the environment."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "real-token")
    backend = ClaudeCustomBackend()
    env = backend._env(_credential(api_key="", config_path=""), tmp_path / "iso")
    assert env["CLAUDE_CONFIG_DIR"] == str((tmp_path / "iso").resolve())
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
