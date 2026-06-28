from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import signal
import struct
import termios
from collections.abc import AsyncIterator


class AsyncPtyHandle:
    """Async wrapper around a PTY subprocess.

    Implements the PtyHandle protocol from protocols/backend.py.
    """

    def __init__(self, master_fd: int, pid: int) -> None:
        self._master_fd = master_fd
        self._pid = pid
        self._closed = False

    @classmethod
    async def spawn(
        cls,
        *,
        command: tuple[str, ...],
        cols: int = 80,
        rows: int = 24,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> AsyncPtyHandle:
        merged_env = {**os.environ, **(env or {})}
        merged_env["TERM"] = merged_env.get("TERM", "xterm-256color")
        master_fd, slave_fd = os.openpty()
        child_pid = os.fork()
        if child_pid == 0:
            # Child process
            # Closes RISKS-AND-BUGS H-5: kill the child if the parent exits
            # unexpectedly. Linux-only via prctl; macOS no-ops (accepted
            # limitation — macOS has no direct equivalent).
            try:
                import ctypes

                libc = ctypes.CDLL("libc.so.6", use_errno=True)
                libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG = 1
            except (OSError, AttributeError):
                pass
            os.close(master_fd)
            os.setsid()
            if cwd:
                with contextlib.suppress(OSError):
                    os.chdir(cwd)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.execvpe(command[0], list(command), merged_env)
        else:
            os.close(slave_fd)
            handle = cls(master_fd, child_pid)
            await handle.resize(cols, rows)
            return handle
        return None

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("handle is closed")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, os.write, self._master_fd, data)

    async def resize(self, cols: int, rows: int) -> None:
        if self._closed:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    async def read(self) -> AsyncIterator[bytes]:
        loop = asyncio.get_event_loop()
        while not self._closed:
            try:
                data = await loop.run_in_executor(None, self._read_once)
                if not data:
                    break
                yield data
            except OSError:
                break

    def _read_once(self) -> bytes:
        try:
            return os.read(self._master_fd, 4096)
        except OSError:
            return b""

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(ProcessLookupError):
            os.kill(self._pid, signal.SIGTERM)
        with contextlib.suppress(OSError):
            os.close(self._master_fd)
        with contextlib.suppress(ChildProcessError):
            # WNOHANG keeps this a non-blocking best-effort reap; run it via a
            # thread so ruff's ASYNC222 (no blocking process waits on the loop)
            # is satisfied without changing the non-blocking semantics.
            await asyncio.to_thread(os.waitpid, self._pid, os.WNOHANG)
