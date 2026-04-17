"""Regression tests for Codex PTY OAuth URL detection.

Ported from Agented commit 78d270c: the Codex CLI's ``login`` command may
emit OAuth URLs on either ``chatgpt.com/auth/...`` (older builds) or
``auth.openai.com/...`` (newer device-code flow). Both must be captured
as ``UrlPrompt`` events so the frontend can auto-open them.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.codex import _CODEX_URL_RE, CodexBackend
from ai_accounts_core.login.events import LoginComplete, UrlPrompt


async def _drain(session):
    return [evt async for evt in session.events()]


def test_codex_url_regex_matches_chatgpt_host():
    m = _CODEX_URL_RE.search("Visit: https://chatgpt.com/auth/device\n")
    assert m is not None
    assert m.group(0) == "https://chatgpt.com/auth/device"


def test_codex_url_regex_matches_auth_openai_host():
    line = (
        "Open the following URL in your browser: "
        "https://auth.openai.com/device?code_challenge=abc123\n"
    )
    m = _CODEX_URL_RE.search(line)
    assert m is not None
    assert m.group(0).startswith("https://auth.openai.com/device")


def test_codex_url_regex_does_not_match_unrelated_hosts():
    # Regression: the generic word "auth" in a path must not match.
    assert _CODEX_URL_RE.search("https://example.com/auth/foo") is None
    assert _CODEX_URL_RE.search("https://api.openai.com/v1/chat") is None


@pytest.mark.asyncio
async def test_codex_oauth_device_captures_auth_openai_url(tmp_path: Path):
    """Codex CLI on newer builds prints auth.openai.com URLs; we must catch them."""
    backend = CodexBackend()
    session = backend.begin_login(
        flow_kind="oauth_device",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    scripted = [
        "Starting OpenAI device flow...\n",
        "Visit: https://auth.openai.com/device?code_challenge=XYZ\n",
        "Enter code: WXYZ-5678\n",
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
    assert url_prompts[0].url.startswith("https://auth.openai.com/device")
    assert url_prompts[0].user_code == "WXYZ-5678"
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_codex_cli_browser_captures_auth_openai_url(tmp_path: Path):
    backend = CodexBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    scripted = [
        "Opening browser...\n",
        "Please visit https://auth.openai.com/authorize?client_id=abc\n",
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
    assert len(url_prompts) == 1
    assert url_prompts[0].url.startswith("https://auth.openai.com/authorize")
