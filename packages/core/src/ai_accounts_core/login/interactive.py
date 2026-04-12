"""Shared interactive CLI login loop.

Claude Code and several other CLIs launch a TUI on first run — a theme
picker, permission prompts, or other menu screens — before accepting
slash-commands like ``/login``. A naive ``read_output`` drain will hang
because the OAuth URL never arrives until the TUI is dismissed.

:func:`run_interactive_cli_login` is an async generator that:

1. Emits an immediate :class:`ProgressUpdate` so the frontend transitions
   out of its "connecting" spinner before any subprocess output arrives.
2. Polls stdout with :meth:`CliOrchestrator.poll_output` on a short slice.
3. On output: strips ANSI, appends to a recent-lines buffer, yields a
   :class:`StdoutChunk`, matches against URL + login-success regexes,
   and — before the action command has been sent — parses menu options.
4. When a menu appears, waits briefly for the menu to finish rendering,
   then emits a :class:`MenuPrompt` with structured options and suspends
   until :meth:`LoginSession.respond` is called. The answer (1-based
   number) is converted to arrow-down-presses + Enter.
5. On idle ticks: if no menu is pending, no action has been sent yet, and
   the CLI has been idle for ``repl_idle_trigger_seconds``, writes the
   action command (e.g. ``/login\r``) — this is how we drive Claude's
   REPL into the OAuth flow after the first-run TUI is dismissed.
6. On :data:`_LOGIN_SUCCESS_RE` match: records the timestamp and force-
   completes after ``login_success_grace_seconds`` of additional idle.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Pattern

from ai_accounts_core.login.cli_orchestrator import (
    CliOrchestrator,
    _LOGIN_SUCCESS_RE,
    _URL_IN_OUTPUT_RE,
    parse_menu_options,
)
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    MenuOption,
    MenuPrompt,
    ProgressUpdate,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)


async def run_interactive_cli_login(
    *,
    orchestrator: CliOrchestrator,
    answers: asyncio.Queue[PromptAnswer],
    progress_label: str,
    action_command: str | None,
    url_regex: Pattern[str] | None = None,
    idle_slice_seconds: float = 1.0,
    repl_idle_trigger_seconds: float = 2.0,
    login_success_grace_seconds: float = 2.0,
    menu_render_grace_seconds: float = 0.3,
    menu_response_timeout: float = 300.0,
) -> AsyncIterator[LoginEvent]:
    """Drive ``orchestrator`` through an interactive CLI login flow.

    Yields :data:`LoginEvent`s. The caller (a :class:`LoginSession` subclass)
    is responsible for ``start()``-ing the orchestrator beforehand and
    terminating it on cancel / on exception.

    ``action_command`` is the slash-command (without trailing CR) sent once
    the CLI has been idle long enough to have landed at its REPL — e.g.
    ``"/login"`` for Claude. Pass ``None`` to skip the re-send entirely
    (for CLIs that print the OAuth URL immediately on startup).

    ``url_regex`` is the backend-specific URL matcher tried before falling
    back to the generic :data:`_URL_IN_OUTPUT_RE`.
    """
    recent_lines: list[str] = []
    action_sent = action_command is None
    login_success_seen = False
    login_success_time = 0.0
    last_output_time = time.monotonic()
    url_already_emitted = False
    pending_menu = False
    pending_menu_options_count = 0

    # Immediate progress so the wizard transitions out of "connecting".
    yield ProgressUpdate(label=progress_label)

    while True:
        try:
            idle_elapsed, chunk = await orchestrator.poll_output(
                timeout=idle_slice_seconds
            )
        except StopAsyncIteration:
            break

        now = time.monotonic()

        if chunk is None:
            # Idle tick.
            idle_since_last_output = now - last_output_time

            # Trigger action command once REPL looks idle.
            if (
                not action_sent
                and not pending_menu
                and recent_lines
                and idle_since_last_output >= repl_idle_trigger_seconds
            ):
                # Double-check no menu is currently on screen.
                if not parse_menu_options(recent_lines):
                    assert action_command is not None
                    await orchestrator.write((action_command + "\r").encode())
                    action_sent = True
                    yield ProgressUpdate(label=f"Sent {action_command}")
                    last_output_time = now
                    continue

            # Force-complete after seeing a success marker + grace period.
            if (
                login_success_seen
                and (now - login_success_time) >= login_success_grace_seconds
            ):
                break
            continue

        # Got output.
        last_output_time = now
        yield StdoutChunk(text=chunk)

        for line in chunk.splitlines():
            recent_lines.append(line)
        if len(recent_lines) > 40:
            recent_lines = recent_lines[-40:]

        # URL detection: backend-specific regex first, then generic.
        if not url_already_emitted:
            m = None
            if url_regex is not None:
                m = url_regex.search(chunk)
            if m is None:
                m = _URL_IN_OUTPUT_RE.search(chunk)
            if m is not None:
                url_already_emitted = True
                yield UrlPrompt(prompt_id="auth", url=m.group(0))

        # Login success detection.
        if not login_success_seen and _LOGIN_SUCCESS_RE.search(chunk):
            login_success_seen = True
            login_success_time = now

        # Menu detection — only before action has been sent. Post-action
        # menus are likely tool confirmations the user shouldn't see.
        if not action_sent and not pending_menu:
            options = parse_menu_options(recent_lines)
            if options:
                # Wait briefly for full menu render (more options may arrive).
                await asyncio.sleep(menu_render_grace_seconds)
                options = parse_menu_options(recent_lines)
                if options:
                    pending_menu = True
                    pending_menu_options_count = len(options)
                    prompt_id = f"menu-{uuid.uuid4().hex[:6]}"
                    yield MenuPrompt(
                        prompt_id=prompt_id,
                        prompt="Choose an option:",
                        options=tuple(
                            MenuOption(
                                number=opt.number,
                                label=opt.label,
                                description=opt.description,
                            )
                            for opt in options
                        ),
                    )

                    # Wait for user response, then send menu selection.
                    try:
                        answer = await asyncio.wait_for(
                            answers.get(), timeout=menu_response_timeout
                        )
                    except asyncio.TimeoutError:
                        break
                    try:
                        chosen = int(answer.answer.strip())
                    except ValueError:
                        chosen = 1
                    chosen_idx = max(
                        0, min(pending_menu_options_count - 1, chosen - 1)
                    )
                    await orchestrator.send_menu_selection(chosen_idx)
                    pending_menu = False
                    recent_lines = []
                    last_output_time = time.monotonic()

    # Loop exit — caller wraps in try/finally to terminate + wait.
    if login_success_seen:
        yield LoginComplete(account_id="", backend_status="validating")
    else:
        yield LoginFailed(
            code="login_incomplete",
            message="CLI login did not report success before EOF / timeout",
        )
