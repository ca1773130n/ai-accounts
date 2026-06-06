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
7. On EVERY iteration (chunk or idle): polls the fake-browser capture file
   for the complete OAuth URL — the CLI's "Opening browser…" spinner keeps
   the PTY busy, so an idle-only check would starve — and runs the URL-wait
   watchdog, failing the session if nothing is detected after the action
   command instead of spinning forever.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from re import Pattern

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Login-loop timing knobs
# ---------------------------------------------------------------------------
#
# These were hardcoded magic numbers in v0.3.7 — every value here is tied to
# real Claude CLI v2.1.x TUI behaviour. Surface them as named constants so
# the timing contract is explicit the next time Claude ships a TUI redraw
# change.
#
# ``IDLE_SLICE_SECONDS`` — how long ``poll_output`` waits for the next chunk
#   before reporting an idle tick. Short enough to feel snappy; long enough
#   that the asyncio queue isn't woken every few ms while the CLI is silent.
#
# ``REPL_IDLE_TRIGGER_SECONDS`` — how long the REPL must stay quiet before we
#   send ``action_command`` (``/login`` for Claude). Claude renders its
#   first-run welcome over ~1.5 s; 2 s is comfortably past that without
#   feeling sluggish.
#
# ``LOGIN_SUCCESS_GRACE_SECONDS`` — after we match a success regex, wait
#   this long with no further output before declaring the flow complete.
#   Claude prints "Logged in as …" then briefly redraws; cutting it off
#   too aggressively can truncate the success card before the user sees it.
#
# ``MENU_RENDER_GRACE_SECONDS`` — the CLI emits a numbered menu in several
#   chunks (header, options, footer). Wait this long with no output before
#   parsing menu options so we don't fire on a half-drawn menu.
#
# ``MENU_RESPONSE_TIMEOUT`` — give the user 5 minutes to pick an option /
#   paste a code. Beyond that we fail the session so a forgotten wizard
#   doesn't hold the PTY indefinitely.
#
# ``EAGER_FOLLOWUP_ENTER_SECONDS`` — Claude v2.1 buffers
#   "Login successful. Press Enter to continue…" behind an internal redraw
#   gate; until another Enter arrives the success line never reaches stdout
#   and our regex stays unmatched. ~5 s is empirically enough for the OAuth
#   token exchange to complete (see backends.claude.write_eager); shorter
#   values race the network call, longer values delay success detection.
IDLE_SLICE_SECONDS: float = 1.0
REPL_IDLE_TRIGGER_SECONDS: float = 2.0
LOGIN_SUCCESS_GRACE_SECONDS: float = 2.0
MENU_RENDER_GRACE_SECONDS: float = 0.3
MENU_RESPONSE_TIMEOUT: float = 300.0
EAGER_FOLLOWUP_ENTER_SECONDS: float = 5.0

# ``URL_WAIT_TIMEOUT_SECONDS`` — how long the loop may run after sending the
#   action command without detecting a URL, a menu, a text prompt, or a
#   success marker before failing the session. Without this, an unrecognized
#   TUI screen (or a URL that both detectors miss) leaves the wizard on its
#   "Preparing sign-in…" spinner *forever* — the CLI's spinner animation
#   keeps producing output, so neither idle-detection nor EOF ever fires.
#   The OAuth URL normally appears within ~5 s of the login-method menu;
#   90 s is generous. NOTE: the timer is disabled once a URL is emitted —
#   the user may legitimately take many minutes to finish OAuth in the
#   browser. It resets whenever the user answers a menu or text prompt.
URL_WAIT_TIMEOUT_SECONDS: float = 90.0


# Small mutable container shared between a backend session's ``write_eager``
# and the interactive login loop. Set ``sent=True`` immediately before writing
# the paste code to the PTY so the text-prompt handler can skip the blocking
# ``answers.get()`` (the CLI already received the code and will either emit
# success or an OAuth-error marker on its own).
@dataclass
class EagerCodeState:
    sent: bool = False
    # Optional redacted preview for operator debugging. The raw code MUST NOT
    # be stored here — OAuth codes are short-lived credentials.
    length: int = 0
    # Monotonic timestamp of the eager write (for computing idle-since-write
    # grace periods from outside the loop).
    at_monotonic: float = 0.0


from ai_accounts_core.login.cli_orchestrator import (
    _LOGIN_SUCCESS_RE,
    _URL_IN_OUTPUT_RE,
    CliOrchestrator,
    parse_menu_options,
)

# A generic-regex match is only trusted when it looks like a *complete* URL:
# dotted host plus a path. Claude's TUI paints the OAuth URL with cursor-
# positioning escapes, which strip_ansi renders as spaces INSIDE the URL
# ("https://cl ud .com/cai/oauth/…") — the permissive _URL_IN_OUTPUT_RE then
# captures a bare fragment like "https://cl". Emitting that would open a
# garbage tab; the complete URL arrives via the fake-browser capture instead.
_PLAUSIBLE_URL_RE = re.compile(r"^https?://[^\s/]+\.[^\s/]+/\S+")

# Text input prompts — lines ending with ">" or ":" that ask for user input.
# Matches: "Paste code here if prompted >", "Enter the code:", "? Question:"
_TEXT_PROMPT_RE = re.compile(
    r"(?:"
    r"(?:paste|enter|type|input)\s+.+[>:]"
    r"|.+\?\s*$"
    r"|\?\s+.+[>:]"
    r"|.+>\s*$"
    r")",
    re.IGNORECASE,
)

# Heuristic token redactor for log lines.  Strips anything that looks like
# an OAuth code / state / token so we never write credential material to
# logs even when the CLI echoes it back in an error message.  The pattern
# matches long (>=20 char) base64url-ish runs plus common "prefix: value"
# shapes like ``code=...`` and ``state=...``.
_TOKEN_REDACT_RE = re.compile(
    r"(?i)"
    r"(?:\b(?:code|state|token|access_token|refresh_token|"
    r"code_verifier|code_challenge|api_key|sk-ant-[A-Za-z0-9_-]*)"
    r"[\s=:]+[A-Za-z0-9._\-#]{8,})"
    r"|(?:[A-Za-z0-9_\-]{24,}#[A-Za-z0-9_\-]{8,})"
    r"|(?:\bsk-ant-[A-Za-z0-9_\-]{10,})"
)


def _redact_tokens(s: str) -> str:
    """Return ``s`` with any credential-shaped substrings replaced by ``<redacted>``."""
    return _TOKEN_REDACT_RE.sub("<redacted>", s)


def _safe_url_origin(url: str) -> str:
    """Return ``scheme://host/path`` with the query string stripped.

    OAuth URLs carry ``state`` and ``code_challenge`` PKCE params plus a
    ``login_hint`` email.  We want to know *which* provider was opened
    without leaking the per-session secrets or PII.
    """
    m = re.match(r"^(https?://[^/\s?#]+)([^\s?#]*)", url)
    if not m:
        return "<url>"
    return m.group(1) + (m.group(2) or "")


def safe_log_text(text: str, *, max_chars: int = 200) -> str:
    """Make ``text`` safe to write to a log line.

    Applies, in order:

    * Token redaction (anything OAuth-code / state / token / api-key shaped)
    * ASCII-only escaping (so terminal control sequences can't drive the
      operator's pager / log viewer through cursor moves or alt-screen
      switches when the log is tailed)
    * Truncation to ``max_chars``

    Use this at every log site that handles untrusted CLI output (chunks,
    error lines, prompts) — that way "I'll just log a snippet for
    debugging" never reintroduces the H2 leak.
    """
    redacted = _redact_tokens(text)
    # ``unicode_escape`` keeps ASCII printables and turns control bytes
    # into their backslash forms, so a CSI sequence ends up as ``\x1b[2J``
    # in the log instead of clearing the operator's screen.
    escaped = redacted.encode("unicode_escape").decode("ascii", errors="replace")
    if len(escaped) > max_chars:
        return escaped[: max_chars - 1] + "…"
    return escaped


# OAuth errors emitted by the CLI after we write a code. These should
# fail the login so the wizard surfaces an error instead of hanging.
_OAUTH_ERROR_RE = re.compile(
    r"(?:"
    r"OAuth\s+error"
    r"|invalid\s+(?:grant|code|token|credentials)"
    r"|authorization\s+code\s+(?:is\s+)?(?:invalid|not\s+found)"
    r"|login\s+failed"
    r"|code\s+(?:has\s+)?expired"
    r"|(?:HTTP|status\s+code)\s+4\d\d"
    r"|401\s+Unauthorized"
    r"|403\s+Forbidden"
    r")",
    re.IGNORECASE,
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
    eager_state: EagerCodeState | None = None,
    idle_slice_seconds: float = IDLE_SLICE_SECONDS,
    repl_idle_trigger_seconds: float = REPL_IDLE_TRIGGER_SECONDS,
    login_success_grace_seconds: float = LOGIN_SUCCESS_GRACE_SECONDS,
    menu_render_grace_seconds: float = MENU_RENDER_GRACE_SECONDS,
    menu_response_timeout: float = MENU_RESPONSE_TIMEOUT,
    eager_followup_enter_seconds: float = EAGER_FOLLOWUP_ENTER_SECONDS,
    url_wait_timeout_seconds: float = URL_WAIT_TIMEOUT_SECONDS,
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
    # Anchor for the URL-wait watchdog: when the action was sent / the last
    # prompt was answered. Mere stdout chunks do NOT reset it — the hang
    # mode this guards against is a CLI spinner producing output forever.
    watchdog_anchor = time.monotonic()

    # Immediate progress so the wizard transitions out of "connecting".
    yield ProgressUpdate(label=progress_label)

    while True:
        try:
            idle_elapsed, chunk = await orchestrator.poll_output(timeout=idle_slice_seconds)
        except StopAsyncIteration:
            break

        now = time.monotonic()

        # Check the fake-browser capture on EVERY iteration — not just idle
        # ticks. While the CLI animates its "Opening browser…" spinner the
        # PTY never goes idle, and the capture file (the only channel that
        # carries the *complete* URL — stdout copies arrive fragmented by
        # TUI cursor-positioning) would otherwise never be read.
        if not url_already_emitted:
            captured = orchestrator.poll_captured_oauth_url()
            if captured:
                url_already_emitted = True
                logger.info(
                    "URL detected via fake-browser capture (%s)", _safe_url_origin(captured)
                )
                yield UrlPrompt(prompt_id="auth", url=captured)

        # URL-wait watchdog: after the action command, *something* must be
        # detected (URL / menu / text prompt / success) within the timeout.
        # Otherwise the CLI is sitting on a screen none of our detectors
        # recognize and the wizard would show its spinner forever.
        if (
            action_sent
            and not url_already_emitted
            and not login_success_seen
            and (now - watchdog_anchor) >= url_wait_timeout_seconds
        ):
            tail = " | ".join(ln.strip() for ln in recent_lines[-3:] if ln.strip())
            logger.warning(
                "url-wait watchdog fired after %.0fs; recent output: %s",
                now - watchdog_anchor,
                safe_log_text(tail),
            )
            yield LoginFailed(
                code="url_wait_timeout",
                message=(
                    "The CLI did not produce a sign-in URL or prompt within "
                    f"{int(url_wait_timeout_seconds)}s. It may be stuck on a screen "
                    f"this wizard does not recognize. Recent CLI output: {tail}"
                )[:300],
            )
            return

        if chunk is None:
            # Idle tick — TUI has stopped outputting.
            idle_since_last_output = now - last_output_time

            # Menu detection during idle — like Agented, we only parse
            # menus after the TUI has gone quiet, ensuring all option
            # lines have arrived across multiple PTY read chunks.
            if (
                not pending_menu
                and recent_lines
                and idle_since_last_output >= menu_render_grace_seconds
            ):
                options = parse_menu_options(recent_lines)
                if options:
                    logger.info(
                        "menu detected (%d options) after %.1fs idle",
                        len(options),
                        idle_since_last_output,
                    )
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

                    # Block until user responds (matches Agented's
                    # threading.Event pattern — no more output processing
                    # until the user picks an option).
                    try:
                        answer = await asyncio.wait_for(
                            answers.get(), timeout=menu_response_timeout
                        )
                    except TimeoutError:
                        yield LoginFailed(
                            code="menu_timeout",
                            message="Menu response timed out",
                        )
                        return
                    try:
                        chosen = int(answer.answer.strip())
                    except ValueError:
                        chosen = 1
                    chosen_idx = max(0, min(pending_menu_options_count - 1, chosen - 1))
                    await orchestrator.send_menu_selection(chosen_idx)
                    pending_menu = False
                    recent_lines = []
                    last_output_time = time.monotonic()
                    watchdog_anchor = last_output_time
                    continue

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
                    watchdog_anchor = now
                    continue

            # Force-complete after seeing a success marker + grace period.
            if login_success_seen and (now - login_success_time) >= login_success_grace_seconds:
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
        # Only log the scheme+host — the full URL contains PKCE state and
        # a login_hint email that we don't need in application logs.
        if not url_already_emitted:
            m = None
            if url_regex is not None:
                m = url_regex.search(chunk)
                if m is not None:
                    logger.info("URL detected via backend regex (%s)", _safe_url_origin(m.group(0)))
            if m is None:
                m = _URL_IN_OUTPUT_RE.search(chunk)
                if m is not None and not _PLAUSIBLE_URL_RE.match(m.group(0)):
                    # Fragment like "https://cl" — see _PLAUSIBLE_URL_RE.
                    logger.info(
                        "generic URL match rejected as fragment (%s)",
                        _safe_url_origin(m.group(0)),
                    )
                    m = None
                if m is not None:
                    logger.info("URL detected via generic regex (%s)", _safe_url_origin(m.group(0)))
            if m is not None:
                url_already_emitted = True
                yield UrlPrompt(prompt_id="auth", url=m.group(0))

        # Login success detection. Intentionally do NOT log the chunk
        # contents — the success line contains the user's email address,
        # and nearby chunks may still hold echoed paste characters.
        if not login_success_seen and _LOGIN_SUCCESS_RE.search(chunk):
            logger.info("login success marker detected")
            login_success_seen = True
            login_success_time = now

        # OAuth error detection — fails the login fast so the wizard
        # doesn't sit forever after the user pastes an invalid code.
        if _OAUTH_ERROR_RE.search(chunk):
            # Pull only the error line itself (not the whole chunk) so
            # surrounding echoed paste characters don't end up in logs.
            error_line = next(
                (ln.strip() for ln in chunk.splitlines() if _OAUTH_ERROR_RE.search(ln)),
                "",
            )
            logger.info("oauth error marker detected: %s", safe_log_text(error_line))
            # Clear the eager flag so an in-session retry (or a fresh
            # session reusing the state object) does not silently swallow
            # the next paste prompt.
            if eager_state is not None:
                eager_state.sent = False
            yield LoginFailed(
                code="oauth_error",
                message=error_line[:200] or "OAuth verification failed",
            )
            return
        # The message above is surfaced to the user via the SSE stream,
        # which is already scoped to an authenticated session — leaving
        # the raw error line in the event body is fine; only the *log
        # line* is redacted.

        # Text input prompt detection — check every chunk, not during idle,
        # because Claude shows a spinner animation while waiting for input
        # which prevents idle from ever triggering.
        if not pending_menu:
            for line in chunk.splitlines():
                stripped = line.strip()
                if stripped and _TEXT_PROMPT_RE.search(stripped):
                    # Eager-write short-circuit: the AccountWizard's
                    # paste-code form already wrote the OAuth code to the
                    # PTY via ``write_eager``. Emitting a TextPrompt now
                    # and blocking on ``answers.get()`` would deadlock —
                    # the frontend UI has been dismissed, the user has
                    # nothing to submit, and the CLI is already processing
                    # the pasted code. Skip this prompt, *consume* the
                    # eager flag (so a second unrelated prompt later in
                    # the same session gets honored normally), and keep
                    # scanning for success / OAuth-error markers.
                    if eager_state is not None and eager_state.sent:
                        eager_state.sent = False
                        logger.info("text prompt skipped — eager code already sent")
                        continue
                    logger.info("text prompt detected")
                    prompt_id = f"text-{uuid.uuid4().hex[:6]}"
                    yield TextPrompt(
                        prompt_id=prompt_id,
                        prompt=stripped,
                        hidden=False,
                    )
                    # Block until user responds — spinner output will queue
                    # up in the reader but we won't process it until the
                    # user submits their answer.
                    try:
                        answer = await asyncio.wait_for(
                            answers.get(), timeout=menu_response_timeout
                        )
                    except TimeoutError:
                        yield LoginFailed(
                            code="prompt_timeout",
                            message="Text input timed out",
                        )
                        return
                    await orchestrator.write((answer.answer.strip() + "\r").encode())
                    # Note: deliberately do NOT flip eager_state.sent here.
                    # eager_state is the contract between ``write_eager``
                    # (eager paste) and the text-prompt handler — the
                    # normal ``respond()`` path is independent. Treating
                    # this write as "eager" would silently swallow the
                    # next prompt, e.g. an in-session "Press Enter to
                    # retry" after a bad code, leaving the wizard hung.

                    # Claude v2 TUI buffers "Login successful. Press Enter
                    # to continue…" behind an internal redraw gate: the
                    # success line never reaches stdout until a second
                    # Enter arrives. Schedule a best-effort follow-up so
                    # the login loop doesn't hang on the regex. On the
                    # error path the extra Enter just dismisses
                    # "Press Enter to retry" — harmless.
                    delay = eager_followup_enter_seconds

                    # Bind `delay` via default arg so each iteration's task
                    # captures its own value — otherwise a later iteration
                    # could reassign `delay` before this task wakes from
                    # asyncio.sleep, sending the wrong follow-up timing.
                    async def _poke_tui_after_paste(delay: float = delay) -> None:
                        await asyncio.sleep(delay)
                        try:
                            await orchestrator.write(b"\r")
                            logger.info("post-paste follow-up Enter sent")
                        except Exception as exc:  # pragma: no cover
                            logger.warning("post-paste follow-up failed: %s", exc)

                    asyncio.create_task(_poke_tui_after_paste())

                    recent_lines = []
                    last_output_time = time.monotonic()
                    watchdog_anchor = last_output_time
                    break  # Only handle one prompt per chunk

    # Loop exit — caller wraps in try/finally to terminate + wait.
    if login_success_seen:
        yield LoginComplete(account_id="", backend_status="validating")
    else:
        yield LoginFailed(
            code="login_incomplete",
            message="CLI login did not report success before EOF / timeout",
        )
