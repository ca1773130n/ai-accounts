from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.backends.goose import GooseBackend
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.login.events import (
    LoginComplete,
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


@pytest.mark.asyncio
async def test_goose_detect_finds_cli():
    backend = GooseBackend()
    with (
        patch("shutil.which", return_value="/opt/bin/goose"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"goose 1.2.3\n", b""))),
    ):
        result = await backend.detect()
    assert result.installed is True
    assert "goose" in (result.version or "").lower()


def test_goose_kind_and_login_flows():
    assert GooseBackend.kind == "goose"
    assert "api_key" in GooseBackend.supported_login_flows


def test_goose_metadata_shape():
    meta = GooseBackend.metadata
    assert meta.kind == "goose"
    assert meta.supports_multi_account is True
    assert meta.isolation_env_var == "GOOSE_PATH_ROOT"
    flow_kinds = {f.kind for f in meta.login_flows}
    assert "api_key" in flow_kinds


def test_goose_env_sets_isolation_and_anthropic_key(tmp_path: Path):
    backend = GooseBackend()
    cred = json.dumps(
        {"provider": "anthropic", "api_key": "sk-ant", "model": "claude-sonnet-4-5"}
    ).encode()
    iso = tmp_path / "iso"
    env = backend._env(cred, iso)
    assert env["GOOSE_PATH_ROOT"] == str(iso.resolve())
    assert env["GOOSE_DISABLE_KEYRING"] == "true"
    assert env["GOOSE_PROVIDER"] == "anthropic"
    assert env["GOOSE_MODEL"] == "claude-sonnet-4-5"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant"


@pytest.mark.parametrize(
    ("provider", "key_env"),
    [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
    ],
)
def test_goose_env_maps_provider_to_key_env(tmp_path: Path, provider: str, key_env: str):
    backend = GooseBackend()
    cred = json.dumps({"provider": provider, "api_key": "K", "model": "m"}).encode()
    env = backend._env(cred, tmp_path)
    assert env[key_env] == "K"
    assert env["GOOSE_PROVIDER"] == provider


@pytest.mark.asyncio
async def test_goose_login_collects_provider_api_key_model(tmp_path: Path):
    backend = GooseBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )
    gen = session.events()

    menu = await gen.__anext__()
    assert isinstance(menu, MenuPrompt)
    await session.respond(PromptAnswer(prompt_id="provider", answer="1"))

    p_key = await gen.__anext__()
    assert isinstance(p_key, TextPrompt)
    assert p_key.prompt_id == "api_key"
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-test"))

    p_model = await gen.__anext__()
    assert isinstance(p_model, TextPrompt)
    assert p_model.prompt_id == "model"
    await session.respond(PromptAnswer(prompt_id="model", answer="claude-sonnet-4-5"))

    complete = await gen.__anext__()
    assert isinstance(complete, LoginComplete)

    assert session.credential is not None
    cred = json.loads(session.credential.decode())
    assert cred == {
        "provider": "anthropic",
        "api_key": "sk-test",
        "model": "claude-sonnet-4-5",
    }
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


@pytest.mark.asyncio
async def test_goose_begin_login_rejects_unknown_flow(tmp_path: Path):
    backend = GooseBackend()
    with pytest.raises(ValueError, match="unsupported"):
        backend.begin_login(
            flow_kind="cli_browser",
            config={},
            vault_ctx={},
            isolation_dir=tmp_path,
        )


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __aiter__(self):
        async def _gen():
            for ln in self._lines:
                yield ln

        return _gen()


class _FakeProc:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = _FakeStdout(lines)
        self.returncode = 0

    async def wait(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_goose_chat_streams_tokens(tmp_path: Path):
    backend = GooseBackend()
    cred = json.dumps({"provider": "anthropic", "api_key": "k", "model": "claude-x"}).encode()
    fake = _FakeProc(
        [
            b'{"content":"Hello"}\n',
            b"not-json\n",
            b"\n",
            b'{"text":" world"}\n',
        ]
    )
    with patch(
        "ai_accounts_core.backends.goose.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        events: list[ChatStreamEvent] = []
        async for e in backend.chat(
            ChatRequest(messages=(_msg("user", "hi"),), model="claude-x"),
            cred,
            isolation_dir=tmp_path,
        ):
            events.append(e)

    tokens = [e.payload for e in events if e.kind == "token"]
    assert tokens == ["Hello", " world"]
    done = next(e for e in events if e.kind == "done")
    assert done.payload["model"] == "claude-x"


@pytest.mark.asyncio
async def test_goose_validate_requires_complete_credential(tmp_path: Path):
    backend = GooseBackend()
    assert await backend.validate(b'{"provider":"anthropic"}', isolation_dir=tmp_path) is False


@pytest.mark.asyncio
async def test_goose_validate_ok_when_info_succeeds(tmp_path: Path):
    backend = GooseBackend()
    cred = json.dumps({"provider": "anthropic", "api_key": "k", "model": "m"}).encode()
    with (
        patch("shutil.which", return_value="/opt/bin/goose"),
        patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"", b""))),
    ):
        assert await backend.validate(cred, isolation_dir=tmp_path) is True


@pytest.mark.asyncio
async def test_goose_chat_yields_only_assistant_text_from_stream_json(tmp_path: Path):
    """A realistic ``goose run --output-format stream-json`` transcript mixes
    assistant text frames with non-text frames (session metadata, tool request
    / response, usage) plus stray partial lines. chat() must surface ONLY the
    assistant text as token events and drop every non-text frame."""
    backend = GooseBackend()
    cred = json.dumps({"provider": "openai", "api_key": "k", "model": "gpt-x"}).encode()
    transcript = [
        # session-start metadata frame — no content/text key
        b'{"type":"session","session_id":"abc123","working_dir":"/tmp/work"}\n',
        # assistant text, streamed in two frames
        b'{"type":"message","role":"assistant","content":"Let me "}\n',
        b'{"type":"message","role":"assistant","content":"check that."}\n',
        # tool request frame — structured args, no assistant text
        b'{"type":"tool_request","id":"t1","tool":"developer__shell",'
        b'"arguments":{"command":"ls -1"}}\n',
        # tool response frame — result payload, no assistant text
        b'{"type":"tool_response","id":"t1","result":{"stdout":"a.txt\\n","exit_code":0}}\n',
        # stray non-JSON flush + blank line the parser must skip
        b"goose: running developer__shell...\n",
        b"\n",
        # final assistant text, then a usage/accounting frame
        b'{"type":"message","role":"assistant","content":" Done."}\n',
        b'{"type":"usage","input_tokens":42,"output_tokens":7}\n',
    ]
    fake = _FakeProc(transcript)
    with patch(
        "ai_accounts_core.backends.goose.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake),
    ):
        events: list[ChatStreamEvent] = []
        async for e in backend.chat(
            ChatRequest(messages=(_msg("user", "list files"),), model="gpt-x"),
            cred,
            isolation_dir=tmp_path,
        ):
            events.append(e)

    tokens = [e.payload for e in events if e.kind == "token"]
    assert tokens == ["Let me ", "check that.", " Done."]
    # Exactly one terminal done event, carrying the requested model.
    done = [e for e in events if e.kind == "done"]
    assert len(done) == 1
    assert done[0].payload["model"] == "gpt-x"
    # No non-text frame leaked through as a token.
    assert all(isinstance(p, str) and p for p in tokens)
