import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.codex import CodexBackend
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginFailed,
    PromptAnswer,
    TextPrompt,
    UrlPrompt,
)


async def _drain(session):
    return [evt async for evt in session.events()]


@pytest.mark.asyncio
async def test_codex_oauth_device_parses_url_and_code(tmp_path: Path):
    backend = CodexBackend()
    session = backend.begin_login(
        flow_kind="oauth_device",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    # Match the actual codex 0.121+ device-auth output: URL on one line,
    # one-time code on its OWN line below the "Enter this one-time code" label.
    scripted = [
        "Follow these steps to sign in:\n",
        "1. Open this link in your browser\n",
        "   https://chatgpt.com/auth/device\n",
        "2. Enter this one-time code\n",
        "   ABCD-1234\n",
        "Waiting...\n",
        "Successfully logged in\n",
    ]

    async def fake_read_output(self):
        for chunk in scripted:
            yield chunk

    with patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.start",
        new=AsyncMock(return_value=None),
    ), patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.read_output",
        fake_read_output,
    ), patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.wait",
        new=AsyncMock(return_value=0),
    ):
        events = await _drain(session)

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(url_prompts) == 1
    assert "chatgpt.com/auth/device" in url_prompts[0].url
    assert url_prompts[0].user_code == "ABCD-1234"
    assert len(completes) >= 1
    assert session.done is True


@pytest.mark.asyncio
async def test_codex_cli_browser_parses_url_and_completion(tmp_path: Path):
    backend = CodexBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    scripted = [
        "Opening browser...\n",
        "Visit: https://chatgpt.com/auth/browser\n",
        "Authentication complete\n",
    ]

    async def fake_read_output(self):
        for chunk in scripted:
            yield chunk

    with patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.start",
        new=AsyncMock(return_value=None),
    ), patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.read_output",
        fake_read_output,
    ), patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.wait",
        new=AsyncMock(return_value=0),
    ):
        events = await _drain(session)

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(url_prompts) == 1
    assert "chatgpt.com/auth/browser" in url_prompts[0].url
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_codex_api_key_accepts_inputs(tmp_path: Path):
    backend = CodexBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-test-anything"))
    events = await events_task

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(text_prompts) == 1
    assert len(completes) == 1


def test_codex_metadata_shape():
    meta = CodexBackend.metadata
    assert meta.kind == "codex"
    assert meta.supports_multi_account is True
    assert meta.isolation_env_var == "CODEX_HOME"
    flow_kinds = {f.kind for f in meta.login_flows}
    # cli_browser was removed from advertised flows because the localhost:1455
    # callback couldn't be reliably driven from a wizard subprocess; only
    # oauth_device + api_key are supported.
    assert "oauth_device" in flow_kinds
    assert "api_key" in flow_kinds
    assert "cli_browser" not in flow_kinds
