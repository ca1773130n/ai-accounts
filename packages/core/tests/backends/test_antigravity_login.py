import asyncio
from pathlib import Path

import pytest
from ai_accounts_core.backends.antigravity import AntigravityBackend
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginFailed,
    PromptAnswer,
    TextPrompt,
)


async def _drain(session):
    return [evt async for evt in session.events()]


@pytest.mark.asyncio
async def test_antigravity_oauth_device_flow_unsupported(tmp_path: Path):
    """Antigravity CLI 0.35+ has no `auth` subcommand; oauth_device is removed."""

    backend = AntigravityBackend()
    with pytest.raises(ValueError, match="unsupported"):
        backend.begin_login(
            flow_kind="oauth_device",
            config={},
            vault_ctx={},
            isolation_dir=tmp_path,
        )


@pytest.mark.asyncio
async def test_antigravity_api_key_accepts_inputs(tmp_path: Path):
    backend = AntigravityBackend()
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
async def test_antigravity_api_key_rejects_empty(tmp_path: Path):
    backend = AntigravityBackend()
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


def test_antigravity_metadata_shape():
    meta = AntigravityBackend.metadata
    assert meta.kind == "antigravity"
    assert meta.supports_multi_account is True
    assert meta.isolation_env_var == "ANTIGRAVITY_HOME"
    flow_kinds = {f.kind for f in meta.login_flows}
    # cli_browser delegates to cliproxyapi --login (Google subscription
    # flow). api_key is kept as fallback for direct AI Studio access.
    assert flow_kinds == {"cli_browser", "api_key"}
