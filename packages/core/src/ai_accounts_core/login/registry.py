"""In-memory LoginSession registry with TTL sweep.

Sessions live in the sidecar process for the duration of the login.
Each session is keyed by its own ``session_id``. Sessions that exceed
``ttl_seconds`` since registration are purged by ``sweep()``.

Concurrency note: all mutation goes through an ``asyncio.Lock`` so the
SSE route handler can safely race with /respond and /cancel.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from ai_accounts_core.login.session import LoginSession


@dataclass
class _Entry:
    session: LoginSession
    registered_at: float


class LoginSessionRegistry:
    def __init__(self, ttl_seconds: float = 600.0) -> None:
        self._entries: dict[str, _Entry] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._pending_cancels: set[asyncio.Task[None]] = set()

    async def register(self, session: LoginSession) -> None:
        async with self._lock:
            if session.session_id in self._entries:
                raise ValueError(f"session {session.session_id!r} already registered")
            self._entries[session.session_id] = _Entry(session, time.monotonic())

    async def get(self, session_id: str) -> LoginSession | None:
        async with self._lock:
            entry = self._entries.get(session_id)
            return entry.session if entry else None

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._entries.pop(session_id, None)

    async def close(self) -> None:
        """Cancel all active sessions and await pending cancel tasks."""
        async with self._lock:
            for entry in list(self._entries.values()):
                if not entry.session.done:
                    try:
                        await entry.session.cancel()
                    except Exception:
                        pass
            self._entries.clear()
        if self._pending_cancels:
            await asyncio.gather(*self._pending_cancels, return_exceptions=True)
        self._pending_cancels.clear()

    async def sweep(self) -> int:
        now = time.monotonic()
        purged = 0
        async with self._lock:
            stale = [
                sid for sid, e in self._entries.items()
                if now - e.registered_at >= self._ttl
            ]
            for sid in stale:
                entry = self._entries.pop(sid)
                purged += 1
                if not entry.session.done:
                    task = asyncio.create_task(entry.session.cancel())
                    self._pending_cancels.add(task)
                    task.add_done_callback(self._pending_cancels.discard)
        return purged
