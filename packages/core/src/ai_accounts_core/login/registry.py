"""In-memory LoginSession registry with TTL sweep.

Sessions live in the sidecar process for the duration of the login.
Each session is keyed by its own ``session_id`` and bound to the
``backend_id`` it was created for. Route handlers must verify both IDs
match before acting on a session — otherwise a leaked session_id could be
used to attach to another backend's login stream or misroute the
resulting credential.

Concurrency note: all mutation goes through an ``asyncio.Lock`` so the
SSE route handler can safely race with /respond and /cancel.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from ai_accounts_core.login.session import LoginSession

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    session: LoginSession
    backend_id: str
    registered_at: float


class LoginSessionRegistry:
    def __init__(self, ttl_seconds: float = 600.0) -> None:
        self._entries: dict[str, _Entry] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._pending_cancels: set[asyncio.Task[None]] = set()

    async def register(self, session: LoginSession, *, backend_id: str) -> None:
        async with self._lock:
            if session.session_id in self._entries:
                raise ValueError(f"session {session.session_id!r} already registered")
            self._entries[session.session_id] = _Entry(
                session=session,
                backend_id=backend_id,
                registered_at=time.monotonic(),
            )
            logger.info(
                "login session registered: sid=%s backend_id=%s kind=%s flow=%s",
                session.session_id,
                backend_id,
                session.backend_kind,
                session.flow_kind,
            )

    async def get(self, session_id: str, *, backend_id: str | None = None) -> LoginSession | None:
        """Return the session iff it exists and, when ``backend_id`` is given,
        it matches the backend the session was registered against.

        Always pass ``backend_id`` from route handlers — omitting it is only
        appropriate for registry-internal bookkeeping. Mismatched backend_id
        returns None (same shape as not-found) so handlers cannot distinguish
        "wrong backend" from "no such session" to avoid probing attacks.
        """
        async with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            if backend_id is not None and entry.backend_id != backend_id:
                logger.warning(
                    "login session %s backend mismatch: registered=%s requested=%s",
                    session_id,
                    entry.backend_id,
                    backend_id,
                )
                return None
            return entry.session

    async def backend_id_for(self, session_id: str) -> str | None:
        async with self._lock:
            entry = self._entries.get(session_id)
            return entry.backend_id if entry else None

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._entries.pop(session_id, None)
            logger.info("login session removed: sid=%s", session_id)

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
            stale = [sid for sid, e in self._entries.items() if now - e.registered_at >= self._ttl]
            for sid in stale:
                entry = self._entries.pop(sid)
                purged += 1
                if not entry.session.done:
                    task = asyncio.create_task(entry.session.cancel())
                    self._pending_cancels.add(task)
                    task.add_done_callback(self._pending_cancels.discard)
        if purged:
            logger.info("swept %d expired login sessions", purged)
        return purged
