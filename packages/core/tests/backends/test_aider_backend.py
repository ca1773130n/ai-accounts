from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.backends.aider import AiderBackend, _AiderApiKeySession
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginFailed,
    MenuPrompt,
    PromptAnswer,
    TextPrompt,
)
from ai_accounts_core.protocols.backend import ChatRequest, PtyRequest


def _credential(
    provider: str = "anthropic", api_key: str = "sk-ant-test", model: str = "sonnet"
) -> bytes:
    return json.dumps({"provider": provider, "api_key": api_key, "model": model}).encode()


def _msg(role: str, content: str) -> ChatMessage:
    return ChatMessage(
        id="m1",
        session_id="s1",
        role=ChatRole(role),
        content=content,
        created_at=datetime.now(UTC),
    )


async def _drain(session) -> list:
    return [evt async for evt in session.events()]


def test_aider_metadata_and_login_flow():
    backend = AiderBackend()
    assert backend.kind == "aider"
    assert backend.metadata.kind == "aider"
    assert backend.supported_login_flows == frozenset({"api_key"})
    assert backend.metadata.isolation_env_var is None
    session = backend.begin_login("api_key", {}, {}, Path("."))
    assert isinstance(session, _AiderApiKeySession)
    assert session.flow_kind == "api_key"
    assert session.backend_kind == "aider"


def test_aider_begin_login_rejects_unknown_flow():
    with pytest.raises(ValueError, match="unsupported"):
        AiderBackend().begin_login("cli_browser", {}, {}, Path("."))


@pytest.mark.asyncio
async def test_aider_login_provider_menu_then_key_then_model(tmp_path: Path):
    """Login emits a provider MenuPrompt, then api_key + model TextPrompts,
    and stores JSON {provider, api_key, model}."""
    backend = AiderBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="provider", answer="1"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-ant-xyz"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="model", answer="sonnet"))
    events = await events_task

    menus = [e for e in events if isinstance(e, MenuPrompt)]
    assert len(menus) == 1
    assert isinstance(events[0], MenuPrompt)
    assert menus[0].prompt_id == "provider"
    assert len(menus[0].options) >= 2

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    assert [p.prompt_id for p in text_prompts] == ["api_key", "model"]
    assert text_prompts[0].hidden is True

    assert any(isinstance(e, LoginComplete) for e in events)
    assert session.credential is not None
    decoded = json.loads(session.credential.decode())
    assert decoded == {"provider": "anthropic", "api_key": "sk-ant-xyz", "model": "sonnet"}


@pytest.mark.asyncio
async def test_aider_login_cancel(tmp_path: Path):
    backend = AiderBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.cancel()
    events = await events_task

    assert any(isinstance(e, LoginFailed) for e in events)
    assert session.credential is None


def test_aider_env_sets_home_to_isolation_dir(tmp_path: Path):
    """HOME points at the resolved isolation dir so the host
    ~/.aider.conf.yml and ~/.env can't leak across accounts."""
    backend = AiderBackend()
    iso = tmp_path / "aider-iso"
    env = backend._env(_credential(provider="anthropic", api_key="sk-ant-test"), iso)
    assert env["HOME"] == str(iso.resolve())
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"


def test_aider_env_provider_key_is_generic(tmp_path: Path):
    backend = AiderBackend()
    env = backend._env(_credential(provider="openrouter", api_key="or-key"), tmp_path)
    assert env["OPENROUTER_API_KEY"] == "or-key"


@pytest.mark.asyncio
async def test_aider_detect_finds_cli():
    backend = AiderBackend()
    with (
        patch("shutil.which", return_value="/opt/bin/aider"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"aider 0.55.0\n", b""))),
    ):
        result = await backend.detect()
    assert result.installed is True


@pytest.mark.asyncio
async def test_aider_pty_returns_handle(tmp_path: Path):
    backend = AiderBackend()
    req = PtyRequest(command=("/bin/echo", "hi"), cols=80, rows=24)
    handle = await backend.pty(req, _credential(), isolation_dir=tmp_path)
    assert hasattr(handle, "read")
    assert hasattr(handle, "write")
    await handle.close()


@pytest.mark.asyncio
async def test_aider_list_models_returns_list(tmp_path: Path):
    models = await AiderBackend().list_models(_credential(), isolation_dir=tmp_path)
    assert isinstance(models, list)


@pytest.mark.asyncio
async def test_aider_get_usage_empty(tmp_path: Path):
    assert await AiderBackend().get_usage(_credential(), isolation_dir=tmp_path) == []


@pytest.mark.asyncio
async def test_aider_chat_one_shot_scrape(tmp_path: Path):
    """chat() is a best-effort one-shot stdout scrape (no token stream)."""
    backend = AiderBackend()

    class _FakeProc:
        async def communicate(self):
            return (b"Edited file foo.py\n", b"")

    with patch(
        "ai_accounts_core.backends.aider.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_FakeProc()),
    ):
        events = [
            e
            async for e in backend.chat(
                ChatRequest(messages=(_msg("user", "do thing"),), model="sonnet"),
                _credential(),
                isolation_dir=tmp_path,
            )
        ]
    assert any(e.kind == "token" and "Edited file" in str(e.payload) for e in events)
    assert any(e.kind == "done" for e in events)
