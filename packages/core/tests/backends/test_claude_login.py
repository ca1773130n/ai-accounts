import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginFailed,
    PromptAnswer,
    TextPrompt,
    UrlPrompt,
)


@pytest.mark.asyncio
async def test_claude_cli_browser_parses_url_and_completion(tmp_path: Path):
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    scripted = [
        "Opening browser...\n",
        "If the browser did not open, visit: https://claude.ai/oauth/authorize?code=XYZ\n",
        "Waiting for authentication...\n",
        "Authentication successful!\n",
    ]

    async def fake_read_output(self):
        for chunk in scripted:
            yield chunk

    with patch(
        "ai_accounts_core.backends.claude.CliOrchestrator.start",
        new=AsyncMock(return_value=None),
    ), patch(
        "ai_accounts_core.backends.claude.CliOrchestrator.read_output",
        fake_read_output,
    ), patch(
        "ai_accounts_core.backends.claude.CliOrchestrator.wait",
        new=AsyncMock(return_value=0),
    ):
        events = [evt async for evt in session.events()]

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(url_prompts) == 1
    assert "https://claude.ai/oauth/authorize?code=XYZ" in url_prompts[0].url
    assert len(completes) == 1
    assert session.done is True


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
