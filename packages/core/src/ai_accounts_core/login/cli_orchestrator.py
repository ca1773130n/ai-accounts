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
import pty
import re
import signal
from collections.abc import AsyncIterator
from pathlib import Path

_CURSOR_POS_RE = re.compile(r"\x1b\[\d*(?:;\d*)*[HfGC]")
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

logger = logging.getLogger(__name__)


def strip_ansi(text: str) -> str:
    text = _CURSOR_POS_RE.sub(" ", text)
    text = _ERASE_SCREEN_RE.sub("\n", text)
    text = _ANSI_RE.sub("", text)
    return text


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

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        pid, master_fd = pty.fork()
        if pid == 0:
            # child
            env = dict(os.environ)
            env.update(self._env)
            for k in _CHILD_ENV_CLEAR:
                env.pop(k, None)
            try:
                os.chdir(self._cwd)
                os.execvpe(self._argv[0], self._argv, env)
            except Exception:  # pragma: no cover - child side
                os._exit(127)
        self._pid = pid
        self._master_fd = master_fd
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
        if self._reader_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            self._master_fd = None
        return self._exit_code

    @property
    def exit_code(self) -> int | None:
        return self._exit_code
