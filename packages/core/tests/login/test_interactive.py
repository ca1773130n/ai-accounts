"""Direct tests for run_interactive_cli_login async generator.

Uses a MockOrchestrator to drive the login loop through idle triggers,
menu detection, URL prompts, success markers, and progress updates.
"""

from __future__ import annotations

import asyncio

from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    ProgressUpdate,
    UrlPrompt,
)
from ai_accounts_core.login.interactive import run_interactive_cli_login


class MockOrchestrator:
    """Replay a scripted sequence of (idle_elapsed, chunk_or_None) tuples."""

    def __init__(self, script: list[tuple[float, str | None]]):
        self._script = list(script)
        self._writes: list[bytes] = []
        self._started = False
        self._terminated = False
        self._menu_selections: list[int] = []

    async def start(self) -> None:
        self._started = True

    async def terminate(self) -> None:
        self._terminated = True

    async def kill(self) -> None:
        self._terminated = True

    async def wait(self) -> int:
        return 0

    async def poll_output(self, timeout: float = 1.0) -> tuple[float, str | None]:
        if not self._script:
            raise StopAsyncIteration
        elapsed, chunk = self._script.pop(0)
        if chunk is None:
            # Actually sleep the elapsed time so time.monotonic() advances
            await asyncio.sleep(elapsed)
        return (elapsed, chunk)

    async def write(self, data: bytes) -> None:
        self._writes.append(data)

    def poll_captured_oauth_url(self) -> str | None:
        return None

    async def send_menu_selection(self, zero_based_index: int) -> None:
        self._menu_selections.append(zero_based_index)
        for _ in range(zero_based_index):
            await self.write(b"\x1b[B")
            await asyncio.sleep(0.01)
        await self.write(b"\r")


async def _collect(
    orch: MockOrchestrator,
    answers: asyncio.Queue | None = None,
    **kwargs,
) -> list[LoginEvent]:
    """Drain events from run_interactive_cli_login."""
    if answers is None:
        answers = asyncio.Queue()
    events: list[LoginEvent] = []
    async for ev in run_interactive_cli_login(
        orchestrator=orch,  # type: ignore[arg-type]
        answers=answers,
        progress_label="Testing",
        idle_slice_seconds=0.05,
        repl_idle_trigger_seconds=0.1,
        login_success_grace_seconds=0.1,
        menu_render_grace_seconds=0.01,
        menu_response_timeout=5.0,
        **kwargs,
    ):
        events.append(ev)
    return events


async def test_sends_action_after_idle():
    """After REPL idle, the action command (/login) is written."""
    orch = MockOrchestrator(
        [
            # Some initial output so recent_lines is non-empty
            (0.0, "Welcome to Claude\n"),
            # Then idle ticks exceeding repl_idle_trigger_seconds
            (0.15, None),
            (0.15, None),
            # EOF
        ]
    )
    await _collect(orch, action_command="/login")
    assert any(b"/login\r" in w for w in orch._writes), (
        f"expected /login\\r in writes, got {orch._writes}"
    )


async def test_detects_menu_and_yields_menu_prompt():
    """Numbered menu lines produce a MenuPrompt with structured options."""
    from ai_accounts_core.login.events import MenuPrompt, PromptAnswer

    answers: asyncio.Queue = asyncio.Queue()
    # Pre-load an answer so the loop doesn't block
    await answers.put(PromptAnswer(prompt_id="any", answer="1"))

    # All menu lines in one chunk so parse_menu_options sees all 3 at once
    menu_block = "❯ 1. Dark mode\n  2. Light mode\n  3. High contrast\n"
    orch = MockOrchestrator(
        [
            (0.0, menu_block),
            # idle after menu
            (0.15, None),
            # EOF
        ]
    )
    events = await _collect(orch, answers=answers, action_command="/login")
    menu_prompts = [e for e in events if isinstance(e, MenuPrompt)]
    assert len(menu_prompts) >= 1, f"expected MenuPrompt, got events: {events}"
    prompt = menu_prompts[0]
    assert prompt.prompt == "Choose an option:"
    assert len(prompt.options) == 3
    assert prompt.options[0].label == "Dark mode"
    assert prompt.options[1].label == "Light mode"
    assert prompt.options[2].label == "High contrast"


async def test_navigates_menu_via_arrow_keys():
    """Choosing option 3 sends 2x down-arrow + enter."""
    from ai_accounts_core.login.events import PromptAnswer

    answers: asyncio.Queue = asyncio.Queue()
    await answers.put(PromptAnswer(prompt_id="any", answer="3"))

    menu_block = "❯ 1. Dark mode\n  2. Light mode\n  3. High contrast\n"
    orch = MockOrchestrator(
        [
            (0.0, menu_block),
            (0.15, None),
            # EOF
        ]
    )
    await _collect(orch, answers=answers, action_command="/login")
    # send_menu_selection(2) -> 2x down-arrow + enter
    assert orch._menu_selections == [2], f"expected [2], got {orch._menu_selections}"
    down_arrows = [w for w in orch._writes if w == b"\x1b[B"]
    enters = [w for w in orch._writes if w == b"\r"]
    assert len(down_arrows) == 2, f"expected 2 down-arrows, got {len(down_arrows)}"
    assert len(enters) >= 1


async def test_emits_url_prompt_after_action():
    """A URL in output after action command yields a UrlPrompt."""
    orch = MockOrchestrator(
        [
            (0.0, "Welcome\n"),
            (0.15, None),  # idle triggers /login
            (0.15, None),
            (0.0, "Visit https://accounts.google.com/o/oauth2/auth?code=abc to login\n"),
            # EOF
        ]
    )
    events = await _collect(orch, action_command="/login")
    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert len(url_prompts) == 1
    assert "https://accounts.google.com" in url_prompts[0].url


async def test_force_completes_on_success_idle():
    """Success marker + idle grace period yields LoginComplete."""
    orch = MockOrchestrator(
        [
            (0.0, "Authentication successful\n"),
            (0.15, None),
            (0.15, None),
        ]
    )
    events = await _collect(orch, action_command=None)
    assert any(isinstance(e, LoginComplete) for e in events), (
        f"expected LoginComplete, got {[type(e).__name__ for e in events]}"
    )


async def test_emits_progress_update_immediately():
    """The very first event yielded is a ProgressUpdate."""
    orch = MockOrchestrator(
        [
            (0.0, "Hello\n"),
        ]
    )
    events = await _collect(orch, action_command=None)
    assert len(events) >= 1
    assert isinstance(events[0], ProgressUpdate), (
        f"expected ProgressUpdate first, got {type(events[0]).__name__}"
    )


class CapturingOrchestrator(MockOrchestrator):
    """MockOrchestrator whose fake-browser capture yields a URL after N polls."""

    def __init__(self, script, captured_url: str, ready_after_polls: int = 2):
        super().__init__(script)
        self._captured_url: str | None = captured_url
        self._polls_until_ready = ready_after_polls

    def poll_captured_oauth_url(self) -> str | None:
        if self._captured_url is None:
            return None
        if self._polls_until_ready > 0:
            self._polls_until_ready -= 1
            return None
        url, self._captured_url = self._captured_url, None
        return url


async def test_captured_url_surfaces_during_continuous_output():
    """The fake-browser capture is read even when the CLI never goes idle.

    Regression: Claude's "Opening browser to sign in…" spinner animates
    continuously, so the PTY never produces an idle tick. The capture file
    (the only channel carrying the COMPLETE OAuth URL) used to be polled
    only during idle — the wizard hung on "Preparing sign-in…" forever.
    """
    spinner_chunks = [(0.0, f"✻ Opening browser to sign in… {i}\n") for i in range(10)]
    orch = CapturingOrchestrator(
        [(0.0, "Welcome\n"), (0.15, None), (0.15, None), *spinner_chunks],
        captured_url="https://claude.com/cai/oauth/authorize?code=true&state=xyz",
        ready_after_polls=4,
    )
    events = await _collect(orch, action_command="/login")
    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert len(url_prompts) == 1, f"expected captured UrlPrompt, got {events}"
    assert url_prompts[0].url == "https://claude.com/cai/oauth/authorize?code=true&state=xyz"


async def test_generic_url_match_rejects_fragments():
    """A cursor-positioning-fragmented URL must not be emitted.

    strip_ansi renders the TUI's column moves as spaces inside the URL
    ("https://cl ud .com/…"); the permissive generic regex then matches the
    bare fragment "https://cl". Opening that in a tab is garbage — the loop
    must wait for the fake-browser capture instead.
    """
    import re

    claude_re = re.compile(r"https://(?:claude\.ai|claude\.com)/\S+")
    orch = MockOrchestrator(
        [
            (0.0, "Welcome\n"),
            (0.15, None),
            (0.15, None),
            (0.0, "Use the url below to sign in https://cl ud .com/cai/oauth/auth\n"),
            (0.15, None),
        ]
    )
    events = await _collect(orch, action_command="/login", url_regex=claude_re)
    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert url_prompts == [], f"fragment must not be emitted, got {url_prompts}"


async def test_watchdog_fails_after_url_wait_timeout():
    """No URL / menu / prompt / success after the action ⇒ LoginFailed.

    Previously the loop idled forever and the wizard showed its spinner
    indefinitely with no feedback.
    """
    from ai_accounts_core.login.events import LoginFailed

    orch = MockOrchestrator(
        [
            (0.0, "Welcome\n"),
            (0.15, None),  # idle → /login sent, watchdog anchored
            (0.15, None),
            (0.15, None),
            (0.15, None),  # > url_wait_timeout_seconds accumulated
            (0.15, None),
            (0.15, None),
        ]
    )
    events = await _collect(orch, action_command="/login", url_wait_timeout_seconds=0.3)
    failed = [e for e in events if isinstance(e, LoginFailed)]
    assert failed, f"expected LoginFailed, got {[type(e).__name__ for e in events]}"
    assert failed[0].code == "url_wait_timeout"
