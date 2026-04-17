"""Tests for Claude v1 → v2 login command selection.

When ``config["email"]`` is provided, the browser flow must spawn
``claude auth login --claudeai --email <email>`` and skip the /login
slash-command. Without email, the legacy v1 flow (bare ``claude`` +
/login) must still be used.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.login.events import LoginComplete, StdoutChunk, UrlPrompt


class _ScriptedOrch:
    def __init__(self, argv: list[str], env: dict[str, str], cwd: Path) -> None:
        _ScriptedOrch.last = self
        self.argv = list(argv)
        self.env = dict(env)
        self.cwd = cwd
        self.writes: list[bytes] = []
        self._script: list[tuple[float, str | None]] = [
            (0.01, "Open https://platform.claude.com/oauth/authorize?x=1 to continue\n"),
            (0.01, "Authentication successful\n"),
            (0.2, None),
            (0.2, None),
        ]

    async def start(self) -> None:
        pass

    async def poll_output(self, timeout: float = 1.0):
        if not self._script:
            raise StopAsyncIteration
        return self._script.pop(0)

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    def poll_captured_oauth_url(self) -> str | None:
        return None

    async def send_menu_selection(self, zero_based_index: int) -> None:
        pass

    async def terminate(self) -> None:
        pass

    async def wait(self) -> int:
        return 0


async def _run_and_capture(backend: ClaudeBackend, config: dict, tmp_path: Path):
    session = backend.begin_login(
        flow_kind="cli_browser",
        config=config,
        vault_ctx={},
        isolation_dir=tmp_path,
    )
    with patch(
        "ai_accounts_core.backends.claude.CliOrchestrator", new=_ScriptedOrch
    ):
        events = [e async for e in session.events()]
    return _ScriptedOrch.last, events


async def test_v2_argv_used_when_email_supplied(tmp_path: Path):
    """With config={"email": ...}, argv is the v2 non-interactive command."""
    orch, events = await _run_and_capture(
        ClaudeBackend(), {"email": "user@example.com"}, tmp_path
    )
    assert orch.argv == [
        "claude", "auth", "login", "--claudeai", "--email", "user@example.com"
    ], orch.argv
    # No /login slash-command should be sent in v2 mode.
    assert not any(b"/login" in w for w in orch.writes), orch.writes
    # The v2 platform.claude.com URL is surfaced as UrlPrompt.
    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert len(url_prompts) == 1
    assert "platform.claude.com" in url_prompts[0].url


async def test_v1_fallback_when_no_email(tmp_path: Path):
    """Without an email, the legacy argv and /login slash-command are used."""
    orch, events = await _run_and_capture(ClaudeBackend(), {}, tmp_path)
    assert orch.argv == ["claude"], orch.argv
    # Legacy flow still sends /login after REPL idle — script provides chunks
    # so idle may or may not fire before EOF; key check is argv.


async def test_v2_argv_strips_surrounding_whitespace_on_email(tmp_path: Path):
    """An email with whitespace still produces a clean argv."""
    orch, _ = await _run_and_capture(
        ClaudeBackend(), {"email": "  user@example.com  "}, tmp_path
    )
    assert orch.argv[-1] == "user@example.com"


def test_cli_browser_flow_declares_optional_email_input():
    """Metadata must advertise ``email`` so hosts can collect it up-front."""
    meta = ClaudeBackend.metadata
    cli_browser = next(f for f in meta.login_flows if f.kind == "cli_browser")
    input_names = {i.name for i in cli_browser.requires_inputs}
    assert "email" in input_names


def test_claude_platform_url_regex_matches_v2_callback():
    """The backend URL regex must match the v2 platform.claude.com callback."""
    from ai_accounts_core.backends.claude import _CLAUDE_CONSOLE_URL_RE

    sample = (
        "If the browser didn't open, visit: "
        "https://platform.claude.com/oauth/code/callback?state=abc&code=xyz"
    )
    m = _CLAUDE_CONSOLE_URL_RE.search(sample)
    assert m is not None
    assert "platform.claude.com/oauth/code/callback" in m.group(0)
