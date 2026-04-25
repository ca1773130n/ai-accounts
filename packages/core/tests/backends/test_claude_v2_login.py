"""Tests for the Claude CLI browser-login flow.

The v2 ``claude auth login --claudeai`` command doesn't read the OAuth
code on stdin (it waits for an HTTP callback on a random local port),
so the backend deliberately always runs the v1 REPL flow
(`claude` + send `/login` into the REPL).  These tests pin that
argv/flow choice and cover the supporting helpers that make the
paste-code path work end-to-end.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend


class _ArgvCapture(Exception):
    """Thrown from the fake CliOrchestrator once it records its argv so
    the login loop exits promptly without needing a full transcript."""


class _ArgvOrch:
    """Minimal fake orchestrator that records its argv and aborts start().

    Used to pin the argv/env selection without running the full
    interactive login loop.
    """

    last: "_ArgvOrch | None" = None

    def __init__(self, argv: list[str], env: dict[str, str], cwd: Path) -> None:
        _ArgvOrch.last = self
        self.argv = list(argv)
        self.env = dict(env)
        self.cwd = cwd

    async def start(self) -> None:
        raise _ArgvCapture()

    async def terminate(self) -> None:  # pragma: no cover - not reached
        pass

    async def wait(self) -> int:  # pragma: no cover - not reached
        return 0


def _consume_until_start(session) -> None:
    """Drive the async generator until it hits the orchestrator start().

    The patched orchestrator raises ``_ArgvCapture`` from ``start``; the
    backend converts any non-FileNotFoundError into a crash, so we catch
    it explicitly here.
    """
    import asyncio

    async def _run() -> None:
        try:
            async for _ in session.events():
                pass
        except _ArgvCapture:
            return
        except Exception as exc:  # pragma: no cover - should not fire
            if not isinstance(exc, _ArgvCapture):
                raise

    asyncio.run(_run())


def test_argv_is_always_v1_repl_regardless_of_email(tmp_path: Path):
    """Even with a supplied email we must use ``["claude"]`` (v1 REPL).

    v2 (`auth login --claudeai --email`) doesn't read stdin, so it can't
    be driven from the wizard — the eager-paste flow + regex detection
    only work against the v1 REPL.  This test pins that decision.
    """
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={"email": "user@example.com"},
        vault_ctx={},
        isolation_dir=tmp_path,
    )
    with patch(
        "ai_accounts_core.backends.claude.CliOrchestrator", new=_ArgvOrch
    ):
        _consume_until_start(session)
    assert _ArgvOrch.last is not None
    assert _ArgvOrch.last.argv == ["claude"], _ArgvOrch.last.argv


def test_argv_is_v1_without_email(tmp_path: Path):
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="cli_browser", config={}, vault_ctx={}, isolation_dir=tmp_path
    )
    with patch(
        "ai_accounts_core.backends.claude.CliOrchestrator", new=_ArgvOrch
    ):
        _consume_until_start(session)
    assert _ArgvOrch.last is not None
    assert _ArgvOrch.last.argv == ["claude"]


@pytest.mark.asyncio
async def test_write_eager_redacts_code_from_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """``write_eager`` must log only the payload *length*, never the code."""
    caplog.set_level(logging.DEBUG, logger="ai_accounts_core.backends.claude")
    secret = "ExtremelySecretOAuthCodeMaterial-AAAAA"

    # Construct the session but stub the orchestrator so the write goes
    # into an in-memory buffer — we only care about the *logging*.
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="cli_browser", config={}, vault_ctx={}, isolation_dir=tmp_path
    )

    class _RecordingOrch:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        async def write(self, data: bytes) -> None:
            self.writes.append(data)

    orch = _RecordingOrch()
    session._orchestrator = orch  # type: ignore[assignment]
    await session.write_eager(secret)

    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in joined, (
        "OAuth code leaked to logs — write_eager must log only the length"
    )
    # Length is still visible for operator debugging.
    assert str(len(secret) + 1) in joined  # +1 for the \r
    # And it actually reached the PTY.
    assert (secret + "\r").encode() in orch.writes


def test_write_eager_sets_eager_state(tmp_path: Path):
    """``write_eager`` must flip the shared ``EagerCodeState.sent`` flag
    *before* awaiting the orchestrator write so a racing text-prompt
    handler can short-circuit."""
    import asyncio

    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="cli_browser", config={}, vault_ctx={}, isolation_dir=tmp_path
    )

    observed_flag = {"sent_at_write_time": None}

    class _ObservingOrch:
        async def write(self, data: bytes) -> None:
            observed_flag["sent_at_write_time"] = session._eager_state.sent

    session._orchestrator = _ObservingOrch()  # type: ignore[assignment]
    asyncio.run(session.write_eager("abc123"))
    assert observed_flag["sent_at_write_time"] is True
    assert session._eager_state.sent is True
    assert session._eager_state.length == len("abc123")


def test_cli_browser_flow_declares_optional_email_input():
    """Metadata must still advertise ``email`` — the wizard pre-fills the
    Claude sign-in page with it, even though argv never carries it."""
    meta = ClaudeBackend.metadata
    cli_browser = next(f for f in meta.login_flows if f.kind == "cli_browser")
    input_names = {i.name for i in cli_browser.requires_inputs}
    assert "email" in input_names


def test_claude_console_url_regex_matches_v2_callback():
    """The URL regex still matches the v2 platform.claude.com callback —
    the v1 REPL prints that same URL as its OAuth fallback link."""
    from ai_accounts_core.backends.claude import _CLAUDE_CONSOLE_URL_RE

    sample = (
        "If the browser didn't open, visit: "
        "https://platform.claude.com/oauth/code/callback?state=abc&code=xyz"
    )
    m = _CLAUDE_CONSOLE_URL_RE.search(sample)
    assert m is not None
    assert "platform.claude.com/oauth/code/callback" in m.group(0)
