import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.gemini import GeminiBackend
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
async def test_gemini_oauth_device_parses_url_and_code(tmp_path: Path):
    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="oauth_device",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    scripted = [
        "Opening device authorization...\n",
        "Visit https://accounts.google.com/o/oauth2/device/usercode\n",
        "Enter code: ZXCV-5678\n",
        "Waiting for authorization...\n",
        "Login successful\n",
    ]

    async def fake_read_output(self):
        for chunk in scripted:
            yield chunk

    with patch(
        "ai_accounts_core.backends.gemini.CliOrchestrator.start",
        new=AsyncMock(return_value=None),
    ), patch(
        "ai_accounts_core.backends.gemini.CliOrchestrator.read_output",
        fake_read_output,
    ), patch(
        "ai_accounts_core.backends.gemini.CliOrchestrator.wait",
        new=AsyncMock(return_value=0),
    ):
        events = await _drain(session)

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(url_prompts) == 1
    assert "accounts.google.com/o/oauth2/device" in url_prompts[0].url
    assert url_prompts[0].user_code == "ZXCV-5678"
    assert len(completes) == 1
    assert session.done is True


@pytest.mark.asyncio
async def test_gemini_api_key_accepts_inputs(tmp_path: Path):
    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="AIzaTestKey"))
    events = await events_task

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(text_prompts) == 1
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_gemini_api_key_rejects_empty(tmp_path: Path):
    backend = GeminiBackend()
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


def test_gemini_metadata_shape():
    meta = GeminiBackend.metadata
    assert meta.kind == "gemini"
    assert meta.supports_multi_account is True
    assert meta.isolation_env_var == "GEMINI_CLI_HOME"
    flow_kinds = {f.kind for f in meta.login_flows}
    assert "oauth_device" in flow_kinds
    assert "api_key" in flow_kinds
