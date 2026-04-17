"""Inline "If the browser didn't open, visit: <URL>" capture regression.

Claude CLI v2 prints the OAuth URL on the same line as the "If the browser
didn't open, visit:" hint. The generic URL regex in the interactive loop
must pick it up, and emit exactly one UrlPrompt regardless of how many
times the same URL appears in subsequent chunks.
"""

from __future__ import annotations

import asyncio

from ai_accounts_core.login.events import LoginEvent, UrlPrompt
from ai_accounts_core.login.interactive import run_interactive_cli_login


class _ReplayOrch:
    def __init__(self, script: list[tuple[float, str | None]]) -> None:
        self._script = list(script)
        self.writes: list[bytes] = []

    async def poll_output(self, timeout: float = 1.0):
        if not self._script:
            raise StopAsyncIteration
        elapsed, chunk = self._script.pop(0)
        if chunk is None:
            await asyncio.sleep(elapsed)
        return (elapsed, chunk)

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    def poll_captured_oauth_url(self) -> str | None:
        return None

    async def send_menu_selection(self, zero_based_index: int) -> None:
        pass


async def _drain(orch: _ReplayOrch) -> list[LoginEvent]:
    events: list[LoginEvent] = []
    answers: asyncio.Queue = asyncio.Queue()
    async for ev in run_interactive_cli_login(
        orchestrator=orch,  # type: ignore[arg-type]
        answers=answers,
        progress_label="test",
        action_command=None,
        idle_slice_seconds=0.05,
        repl_idle_trigger_seconds=0.1,
        login_success_grace_seconds=0.1,
        menu_render_grace_seconds=0.01,
        menu_response_timeout=1.0,
    ):
        events.append(ev)
    return events


async def test_inline_visit_url_extracted_once():
    """The URL on a 'visit:' line is emitted exactly once even if the CLI
    re-prints it (idle frame repaints / reminder prompts)."""
    url = "https://platform.claude.com/oauth/authorize?state=abc"
    orch = _ReplayOrch([
        (0.01, f"If the browser didn't open, visit: {url}\n"),
        # CLI re-prints a reminder shortly after — must NOT produce a second
        # UrlPrompt.
        (0.01, f"Still waiting… visit: {url}\n"),
        (0.01, "Authentication successful\n"),
        (0.15, None),
        (0.15, None),
    ])
    events = await _drain(orch)
    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert len(url_prompts) == 1, (
        f"expected exactly one UrlPrompt, got {len(url_prompts)}: "
        f"{[p.url for p in url_prompts]}"
    )
    assert url_prompts[0].url.startswith(url)


async def test_long_url_not_wrapped_at_80_cols():
    """The 500-col PTY (set in CliOrchestrator.start) means a 400-char URL
    arrives as a single continuous chunk — no wrapping. We simulate that
    here by feeding the long URL in one chunk and checking it is captured
    whole.
    """
    long_url = "https://platform.claude.com/oauth/authorize?state=" + ("x" * 400)
    orch = _ReplayOrch([
        (0.01, f"visit: {long_url}\n"),
        (0.01, "Authentication successful\n"),
        (0.15, None),
        (0.15, None),
    ])
    events = await _drain(orch)
    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert len(url_prompts) == 1
    assert url_prompts[0].url == long_url
