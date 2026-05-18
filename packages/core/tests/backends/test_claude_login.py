import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginFailed,
    ProgressUpdate,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)


@pytest.mark.asyncio
async def test_claude_cli_browser_interactive_loop_drives_url_and_completion(tmp_path: Path):
    """Drive the interactive loop via mocked poll_output.

    Scripts: welcome blurb → idle (triggers /login send) → URL appears →
    login success marker → idle (force-complete).
    """
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    # Each entry is (idle_elapsed, chunk_or_None). None = timeout/idle tick.
    # The loop needs enough idle time (>= repl_idle_trigger_seconds = 2s) to
    # fire the /login send; we emit idle ticks with elapsed that the loop
    # sees via time.monotonic — so instead fake time.monotonic.
    scripted: list[tuple[float, str | None]] = [
        (0.01, "Welcome to Claude Code!\n"),
        (0.01, "Type your prompt below.\n"),
        (1.0, None),  # idle tick #1
        (1.0, None),  # idle tick #2 — at this point time-since-last-output >= 2s
        (0.01, "Open this URL: https://claude.ai/oauth/authorize?code=XYZ\n"),
        (0.01, "Waiting for authentication...\n"),
        (0.01, "Authentication successful!\n"),
        (1.0, None),  # first grace tick
        (1.0, None),  # second grace tick — force-complete (>= 2s)
    ]
    script_iter = iter(scripted)

    async def fake_poll(self, timeout: float = 1.0):
        try:
            item = next(script_iter)
        except StopIteration:
            raise StopAsyncIteration
        return item

    writes: list[bytes] = []

    async def fake_write(self, data: bytes) -> None:
        writes.append(data)

    # Freeze time.monotonic and advance it as the loop polls so idle math works.
    current_time = [0.0]

    def fake_monotonic() -> float:
        return current_time[0]

    real_poll_orig = fake_poll

    async def poll_advancing(self, timeout: float = 1.0):
        res = await real_poll_orig(self, timeout=timeout)
        elapsed, chunk = res
        current_time[0] += elapsed if chunk is not None else timeout
        return res

    with (
        patch(
            "ai_accounts_core.backends.claude.CliOrchestrator.start",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "ai_accounts_core.login.cli_orchestrator.CliOrchestrator.poll_output",
            poll_advancing,
        ),
        patch(
            "ai_accounts_core.login.cli_orchestrator.CliOrchestrator.write",
            fake_write,
        ),
        patch(
            "ai_accounts_core.login.cli_orchestrator.CliOrchestrator.terminate",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "ai_accounts_core.login.cli_orchestrator.CliOrchestrator.wait",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "ai_accounts_core.login.interactive.time.monotonic",
            fake_monotonic,
        ),
    ):
        events = [evt async for evt in session.events()]

    # First event must be ProgressUpdate so the wizard transitions out of
    # "connecting" immediately.
    assert isinstance(events[0], ProgressUpdate)
    assert "claude" in events[0].label.lower()

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    stdout_chunks = [e for e in events if isinstance(e, StdoutChunk)]

    assert len(url_prompts) == 1
    assert "oauth/authorize?code=XYZ" in url_prompts[0].url
    assert len(completes) == 1
    assert len(stdout_chunks) >= 1
    assert session.done is True

    # The loop should have sent /login exactly once after REPL idle.
    login_writes = [w for w in writes if b"/login" in w]
    assert len(login_writes) == 1, writes


async def _drain(session):
    return [evt async for evt in session.events()]


@pytest.mark.asyncio
async def test_claude_api_key_accepts_inputs(tmp_path: Path):
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-ant-test"))
    events = await events_task

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(text_prompts) == 1
    assert text_prompts[0].prompt_id == "api_key"
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_claude_api_key_rejects_bad_prefix(tmp_path: Path):
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="bad-key"))
    events = await events_task

    failures = [e for e in events if isinstance(e, LoginFailed)]
    assert len(failures) == 1
    assert failures[0].code == "invalid_key"


def test_claude_metadata_shape():
    meta = ClaudeBackend.metadata
    assert meta.kind == "claude"
    assert meta.supports_multi_account is True
    assert meta.isolation_env_var == "CLAUDE_CONFIG_DIR"
    flow_kinds = {f.kind for f in meta.login_flows}
    assert "cli_browser" in flow_kinds
    assert "api_key" in flow_kinds
