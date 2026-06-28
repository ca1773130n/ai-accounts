from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.backends.crush import CrushBackend, _CrushApiKeySession
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginFailed,
    MenuPrompt,
    PromptAnswer,
    TextPrompt,
)
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent


def _msg(role: str, content: str) -> ChatMessage:
    return ChatMessage(
        id="m1",
        session_id="s1",
        role=ChatRole(role),
        content=content,
        created_at=datetime.now(UTC),
    )


def _credential(
    provider: str = "anthropic", api_key: str = "sk-crush-test", model: str = ""
) -> bytes:
    return json.dumps({"provider": provider, "api_key": api_key, "model": model}).encode()


async def _drain(session) -> list:
    return [evt async for evt in session.events()]


def test_crush_metadata_and_login_flow():
    backend = CrushBackend()
    assert backend.kind == "crush"
    assert backend.metadata.kind == "crush"
    assert backend._CLI_NAME == "crush"
    assert "api_key" in backend.supported_login_flows
    session = backend.begin_login("api_key", {}, {}, Path("."))
    assert isinstance(session, _CrushApiKeySession)
    assert session.flow_kind == "api_key"
    assert session.backend_kind == "crush"


def test_crush_begin_login_rejects_unknown_flow():
    backend = CrushBackend()
    with pytest.raises(ValueError, match="unsupported"):
        backend.begin_login("cli_browser", {}, {}, Path("."))


@pytest.mark.asyncio
async def test_crush_login_writes_isolated_crush_json(tmp_path: Path):
    """Login emits a provider MenuPrompt, then api_key + model TextPrompts, and
    persists an isolated crush.json under the isolation dir containing the
    chosen provider + api_key. Credential is JSON {provider, api_key, model}."""
    backend = CrushBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="provider", answer="1"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-ant-xyz"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="model", answer="claude-sonnet-4-5"))
    events = await events_task

    menus = [e for e in events if isinstance(e, MenuPrompt)]
    assert len(menus) == 1
    assert isinstance(events[0], MenuPrompt)
    assert menus[0].prompt_id == "provider"
    assert len(menus[0].options) >= 2

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    assert [p.prompt_id for p in text_prompts] == ["api_key", "model"]
    assert text_prompts[0].hidden is True

    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(completes) == 1

    # Credential JSON shape.
    assert session.credential is not None
    decoded = json.loads(session.credential.decode())
    assert decoded == {
        "provider": "anthropic",
        "api_key": "sk-ant-xyz",
        "model": "claude-sonnet-4-5",
    }

    # Isolated crush.json written under the isolation dir with provider + key.
    config_path = tmp_path / "crush.json"
    assert config_path.is_file()
    written = json.loads(config_path.read_text())
    assert "anthropic" in written["providers"]
    assert written["providers"]["anthropic"]["api_key"] == "sk-ant-xyz"


@pytest.mark.asyncio
async def test_crush_login_rejects_empty_key(tmp_path: Path):
    backend = CrushBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="provider", answer="1"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer=""))
    events = await events_task

    failures = [e for e in events if isinstance(e, LoginFailed)]
    assert len(failures) == 1
    assert failures[0].code == "invalid_key"
    assert session.credential is None


@pytest.mark.asyncio
async def test_crush_login_cancel(tmp_path: Path):
    backend = CrushBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.cancel()
    events = await events_task

    assert any(isinstance(e, LoginFailed) for e in events)
    assert session.credential is None


def test_crush_env_sets_global_config_and_data(tmp_path: Path):
    backend = CrushBackend()
    env = backend._env(_credential(), tmp_path)
    iso = tmp_path.resolve()
    assert env["CRUSH_GLOBAL_CONFIG"] == str(iso / "crush.json")
    assert env["CRUSH_GLOBAL_DATA"] == str(iso / "data")
    # _env also (re)writes the isolated config from the credential so a PTY
    # session works after a credential restore (no re-login).
    config_path = iso / "crush.json"
    assert config_path.is_file()
    written = json.loads(config_path.read_text())
    assert written["providers"]["anthropic"]["api_key"] == "sk-crush-test"


@pytest.mark.asyncio
async def test_crush_chat_yields_error_tui_only(tmp_path: Path):
    backend = CrushBackend()
    events: list[ChatStreamEvent] = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="claude-sonnet-4-5"),
        _credential(),
        isolation_dir=tmp_path,
    ):
        events.append(e)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "TUI" in str(events[0].payload) or "tui" in str(events[0].payload).lower()


@pytest.mark.asyncio
async def test_crush_list_models_fallback(tmp_path: Path):
    models = await CrushBackend().list_models(_credential(), isolation_dir=tmp_path)
    assert isinstance(models, list)


@pytest.mark.asyncio
async def test_crush_get_usage_empty(tmp_path: Path):
    assert await CrushBackend().get_usage(_credential(), isolation_dir=tmp_path) == []


@pytest.mark.asyncio
async def test_crush_detect_finds_cli():
    backend = CrushBackend()
    with (
        patch("shutil.which", return_value="/opt/bin/crush"),
        patch.object(
            backend, "_run", new=AsyncMock(return_value=(0, b"crush version 0.79.0\n", b""))
        ),
    ):
        result = await backend.detect()
    assert result.installed is True
    assert result.version is not None
