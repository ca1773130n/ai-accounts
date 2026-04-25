"""PTY-based CLI subprocess orchestrator.

Ported from Agented's backend/app/services/pty_service.py +
backend_cli_service.py. Runs a child CLI inside a pseudo-terminal so tools
that require TTY (claude, codex, interactive gemini) launch correctly.
Streams ANSI-stripped output as async str chunks, accepts stdin writes,
supports graceful terminate + wait.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import signal
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

# Cursor movements that imply a new row (absolute positioning).
_CURSOR_ROW_RE = re.compile(r"\x1b\[\d*(?:;\d*)*[Hf]")
# Cursor movements that stay on the same row (column-only).
_CURSOR_COL_RE = re.compile(r"\x1b\[\d*[GC]")
_ERASE_SCREEN_RE = re.compile(r"\x1b\[\d*J")
_ANSI_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[\x20-\x3f]*[\x40-\x7e]"
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|[()][AB012]"
    r"|[\x40-\x5f]"
    r")"
    r"|\x0f|\x0e"
)

_CHILD_ENV_CLEAR = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")

# Numbered menu: "❯ 1. Dark mode ✔" / "  2. Light mode" / "● 3 Option · description"
#
# Match any of three forms:
#   (a) optional ❯/●/○/◉ bullet + ``N. label``           (dotted, original)
#   (b) ●/○/◉ bullet + ``N label · description``          (bullet, no dot)
#   (c) optional ❯/●/○/◉ bullet + ``N label · description``
#       — Claude CLI v2.1.119 dropped the ``.`` after the digit; the ``·``
#       between label and description is what disambiguates from diff hunks
#       like ``2 - console.log("Hello")`` so we still don't false-positive
#       on plain ``N word`` lines.
_NUMBERED_OPTION_RE = re.compile(
    r"^\s*(?:"
    r"[❯●○◉]?\s*(?P<num>\d+)\.\s+(?P<label>.+?)(?:\s*·\s*(?P<desc>.+))?"
    r"|"
    r"[●○◉]\s*(?P<num2>\d+)\s+(?P<label2>.+?)(?:\s*·\s*(?P<desc2>.+))?"
    r"|"
    r"[❯●○◉]?\s*(?P<num3>\d+)\s+(?P<label3>.+?)\s*·\s*(?P<desc3>.+)"
    r")\s*$"
)

# Login success markers — fires force-complete path when seen in stdout.
_LOGIN_SUCCESS_RE = re.compile(
    r"(?:"
    r"successfully\s+(?:logged|authenticated|signed|acquired)"
    r"|auth\s+code\s+was\s+successfully\s+acquired"
    r"|(?:now\s+)?logged\s+in(?:\s+as\b|\.\s|\.$|:\s|\s+MCP\b)"
    r"|signed\s+in\s+(?:as|with)\b"
    r"|authentication\s+(?:successful|complete)"
    r"|login\s+(?:successful|complete)"
    r"|you\s+are\s+(?:now\s+)?logged\s+in"
    r"|account\s+(?:added|connected|linked)"
    r"|✓\s*(?:signed|logged|authenticated)"
    r")",
    re.IGNORECASE,
)

# Permissive URL matcher for OAuth flows printed in CLI output.
_URL_IN_OUTPUT_RE = re.compile(r"https?://[^\s\"'<>]+")


@dataclass
class MenuOption:
    """A single numbered option parsed from a CLI menu."""

    number: int
    label: str
    description: str | None = None


def parse_menu_options(recent_lines: list[str]) -> list[MenuOption]:
    """Scan ``recent_lines`` for numbered menu options in display order.

    Dedupes by option number: menus that redraw on terminal repaint will
    emit the same option multiple times — keep the first occurrence.
    """
    options: list[MenuOption] = []
    seen_numbers: set[int] = set()
    for line in recent_lines:
        m = _NUMBERED_OPTION_RE.match(line)
        if not m:
            continue
        num_str = m.group("num") or m.group("num2") or m.group("num3")
        label = m.group("label") or m.group("label2") or m.group("label3")
        desc = m.group("desc") or m.group("desc2") or m.group("desc3")
        if num_str is None or label is None:
            continue
        num = int(num_str)
        if num in seen_numbers:
            continue
        seen_numbers.add(num)
        options.append(
            MenuOption(
                number=num,
                label=label.strip(),
                description=desc.strip() if desc else None,
            )
        )
    return options


logger = logging.getLogger(__name__)


# Detect a trailing incomplete escape: ESC followed by chars that look like
# the start of a CSI/OSC sequence but haven't reached a final byte yet.
_TRAILING_ESC_RE = re.compile(r"\x1b(?:\[[\x20-\x3f]*|\][^\x07\x1b]*)$")


def strip_ansi(text: str) -> str:
    text = _CURSOR_ROW_RE.sub("\n", text)
    text = _CURSOR_COL_RE.sub(" ", text)
    text = _ERASE_SCREEN_RE.sub("\n", text)
    text = _ANSI_RE.sub("", text)
    return text


def strip_ansi_buffered(text: str) -> tuple[str, str]:
    """Strip ANSI escapes, returning (clean_text, leftover).

    ``leftover`` is a trailing incomplete escape sequence that should be
    prepended to the next chunk before stripping again.
    """
    leftover = ""
    m = _TRAILING_ESC_RE.search(text)
    if m:
        leftover = text[m.start():]
        text = text[:m.start()]
    return strip_ansi(text), leftover


class CliOrchestrator:
    """Runs ``argv`` inside a PTY, exposes stdout as async chunks and stdin as ``write()``."""

    def __init__(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
    ) -> None:
        self._argv = argv
        self._env = env
        self._cwd = cwd
        self._pid: int | None = None
        self._master_fd: int | None = None
        self._exit_code: int | None = None
        self._reader_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._started = False
        self._ansi_leftover: str = ""
        self._oauth_url_file: Path | None = None
        self._fake_browser_path: Path | None = None
        self._fake_bin_dir: Path | None = None

    async def start(self) -> None:
        if self._started:
            return
        self._started = True

        # Create a fake browser/open script that captures OAuth URLs to a
        # temp file instead of opening a real browser on the server.
        # On macOS, CLIs use `open` (ignores BROWSER env var), so we also
        # put a fake `open` at the front of PATH.
        self._oauth_url_file = Path(tempfile.mktemp(suffix=".oauth-url"))
        self._fake_bin_dir = Path(tempfile.mkdtemp(suffix="-fake-bin"))
        url_file = str(self._oauth_url_file)

        # Fake script: capture the last URL-like argument to file
        script = (
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  case \"$arg\" in\n"
            f"    http://*|https://*) echo \"$arg\" > {url_file} ;;\n"
            "  esac\n"
            "done\n"
        )
        for name in ("open", "xdg-open"):
            p = self._fake_bin_dir / name
            p.write_text(script)
            p.chmod(0o755)
        self._fake_browser_path = self._fake_bin_dir

        pid, master_fd = os.forkpty()
        if pid == 0:
            # child
            import fcntl
            import struct
            import termios

            # Closes RISKS-AND-BUGS H-5: ensure the child is killed if the
            # parent crashes before reaching wait(). prctl(PR_SET_PDEATHSIG)
            # is Linux-only; macOS silently no-ops via the OSError branch,
            # which we accept as a platform limitation.
            try:
                import ctypes

                libc = ctypes.CDLL("libc.so.6", use_errno=True)
                libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG = 1
            except (OSError, AttributeError):
                pass

            # Set wide terminal (500 cols) so OAuth URLs don't wrap
            winsize = struct.pack("HHHH", 50, 500, 0, 0)
            try:
                fcntl.ioctl(1, termios.TIOCSWINSZ, winsize)
            except OSError:
                pass

            env = dict(os.environ)
            env.update(self._env)
            for k in _CHILD_ENV_CLEAR:
                env.pop(k, None)
            # Prepend fake bin dir so our fake `open`/`xdg-open` is found
            # first. Also set BROWSER for tools that respect it.
            env["PATH"] = str(self._fake_bin_dir) + ":" + env.get("PATH", "")
            env["BROWSER"] = str(self._fake_bin_dir / "open")
            try:
                os.chdir(self._cwd)
                os.execvpe(self._argv[0], self._argv, env)
            except Exception:  # pragma: no cover - child side
                os._exit(127)
            os._exit(127)  # belt-and-suspenders: execvpe shouldn't return on success
        self._pid = pid
        self._master_fd = master_fd
        # Also set wide terminal from parent side
        import fcntl
        import struct
        import termios
        winsize = struct.pack("HHHH", 50, 500, 0, 0)
        with contextlib.suppress(OSError):
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        assert self._master_fd is not None
        loop = asyncio.get_running_loop()
        try:
            while True:
                try:
                    data = await loop.run_in_executor(None, self._read_once)
                except OSError:
                    break
                if not data:
                    break
                await self._reader_queue.put(data)
        finally:
            await self._reader_queue.put(None)

    def _read_once(self) -> bytes:
        assert self._master_fd is not None
        try:
            return os.read(self._master_fd, 4096)
        except OSError:
            return b""

    async def poll_output(self, timeout: float = 1.0) -> tuple[float, str | None]:
        """Wait up to ``timeout`` for the next ANSI-stripped output chunk.

        Returns ``(idle_elapsed_seconds, chunk_or_None)``. On timeout the
        chunk is ``None`` and ``idle_elapsed_seconds`` is roughly ``timeout``.
        Raises :class:`StopAsyncIteration` when the reader has hit EOF.
        """
        start = time.monotonic()
        try:
            item = await asyncio.wait_for(self._reader_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return (time.monotonic() - start, None)
        if item is None:
            raise StopAsyncIteration
        raw = self._ansi_leftover + item.decode(errors="replace")
        clean, self._ansi_leftover = strip_ansi_buffered(raw)
        return (time.monotonic() - start, clean)

    async def send_menu_selection(self, zero_based_index: int) -> None:
        """Send arrow-down * N + Enter to pick option at ``zero_based_index``."""
        for _ in range(zero_based_index):
            await self.write(b"\x1b[B")
            await asyncio.sleep(0.05)
        await self.write(b"\r")

    def poll_captured_oauth_url(self) -> str | None:
        """Check if the fake browser captured an OAuth URL.

        Returns the URL string if found, None otherwise. Deletes the file
        after reading so each URL is only returned once.
        """
        if self._oauth_url_file and self._oauth_url_file.exists():
            url = self._oauth_url_file.read_text().strip()
            self._oauth_url_file.unlink(missing_ok=True)
            return url if url else None
        return None

    async def read_output(self) -> AsyncIterator[str]:
        """Yield ANSI-stripped output chunks until EOF."""
        buf = b""
        while True:
            item = await self._reader_queue.get()
            if item is None:
                if buf:
                    yield strip_ansi(buf.decode(errors="replace"))
                return
            buf += item
            if b"\n" in item or len(buf) > 1024:
                text = buf.decode(errors="replace")
                buf = b""
                yield strip_ansi(text)

    async def write(self, data: bytes) -> None:
        if self._master_fd is None:
            raise RuntimeError("orchestrator not started")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, os.write, self._master_fd, data)

    async def terminate(self) -> None:
        if self._pid is None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.kill(self._pid, signal.SIGTERM)
        # Close master_fd so the reader thread unblocks
        if self._master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            self._master_fd = None

    async def kill(self) -> None:
        if self._pid is None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.kill(self._pid, signal.SIGKILL)

    async def wait(self) -> int:
        if self._pid is None:
            return self._exit_code or 0
        loop = asyncio.get_running_loop()
        _, status = await loop.run_in_executor(None, os.waitpid, self._pid, 0)
        if os.WIFEXITED(status):
            self._exit_code = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            self._exit_code = -os.WTERMSIG(status)
        else:
            self._exit_code = -1
        self._pid = None
        if self._reader_task is not None:
            if not self._reader_task.done():
                self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            self._master_fd = None
        # Clean up fake browser temp files
        if self._fake_bin_dir and self._fake_bin_dir.exists():
            import shutil
            shutil.rmtree(self._fake_bin_dir, ignore_errors=True)
        if self._oauth_url_file:
            self._oauth_url_file.unlink(missing_ok=True)
        return self._exit_code

    @property
    def exit_code(self) -> int | None:
        return self._exit_code
