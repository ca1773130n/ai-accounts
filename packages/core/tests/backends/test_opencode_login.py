import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.opencode import OpenCodeBackend
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
async def test_opencode_cli_browser_parses_url_and_completion(tmp_path: Path):
    backend = OpenCodeBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    scripted = [
        "Starting OpenCode auth...\n",
        "Open: https://opencode.ai/auth/callback\n",
        "Authentication successful\n",
    ]

    async def fake_read_output(self):
        for chunk in scripted:
            yield chunk

    with patch(
        "ai_accounts_core.backends.opencode.CliOrchestrator.start",
        new=AsyncMock(return_value=None),
    ), patch(
        "ai_accounts_core.backends.opencode.CliOrchestrator.read_output",
        fake_read_output,
    ), patch(
        "ai_accounts_core.backends.opencode.CliOrchestrator.wait",
        new=AsyncMock(return_value=0),
    ):
        events = await _drain(session)

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(url_prompts) == 1
    assert "opencode.ai/auth/callback" in url_prompts[0].url
    assert len(completes) == 1
    assert session.done is True


@pytest.mark.asyncio
async def test_opencode_api_key_accepts_inputs(tmp_path: Path):
    backend = OpenCodeBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="oc-test-key"))
    events = await events_task

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(text_prompts) == 1
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_opencode_api_key_rejects_empty(tmp_path: Path):
    backend = OpenCodeBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer=""))
    events = await events_task

    failures = [e for e in events if isinstance(e, LoginFailed)]
    assert len(failures) == 1
    assert failures[0].code == "invalid_key"


def test_opencode_metadata_shape():
    meta = OpenCodeBackend.metadata
    assert meta.kind == "opencode"
    assert meta.supports_multi_account is True
    assert meta.isolation_env_var == "OPENCODE_HOME"
    flow_kinds = {f.kind for f in meta.login_flows}
    assert "cli_browser" in flow_kinds
    assert "api_key" in flow_kinds
