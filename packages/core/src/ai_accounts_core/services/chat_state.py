from __future__ import annotations

import collections
import copy
import logging
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplayResult:
    """Result of a cursor-based replay.

    ``events`` is a list of events strictly newer than the client's cursor (or
    the full retained log when the cursor predates the oldest retained seq).
    ``gap`` is True when the client's ``last_seq`` is older than the oldest
    retained seq, meaning some events between the cursor and the returned
    events have been evicted and will never be delivered. Clients should
    treat this as a recovery signal (re-sync full state) rather than assume
    contiguous history.
    """
    events: list[dict[str, Any]]
    gap: bool


class ChatStateService:
    """Seq-numbered event log with cursor-based replay for SSE reconnection.

    Concurrency: a single registry lock guards the session map; each session
    has its own lock so unrelated sessions don't serialize on each other's
    ``push_event`` / ``replay`` calls.

    Mutation hygiene: events returned from ``replay`` / ``get_event_log`` are
    deep-copied so callers mutating a returned dict cannot corrupt the
    retained log.
    """

    def __init__(self, *, max_events: int = 1000) -> None:
        self._max_events = max_events
        self._sessions: dict[str, _SessionState] = {}
        self._registry_lock = threading.Lock()

    def _get_state(self, session_id: str) -> _SessionState | None:
        with self._registry_lock:
            return self._sessions.get(session_id)

    def init_session(self, session_id: str, *, start_seq: int = 0) -> None:
        """Create or reset a session state. ``start_seq`` seeds the seq
        counter; used on reconnect after eviction so new events don't collide
        with a client's retained ``lastSeq``.

        Note: this unconditionally replaces any existing session state. Callers
        that want to preserve existing state on reconnect should check with
        ``get_event_log`` first.
        """
        with self._registry_lock:
            self._sessions[session_id] = _SessionState(
                max_events=self._max_events, start_seq=start_seq
            )

    def remove_session(self, session_id: str) -> None:
        with self._registry_lock:
            self._sessions.pop(session_id, None)

    def push_event(self, session_id: str, event: dict[str, Any]) -> int:
        state = self._get_state(session_id)
        if state is None:
            logger.warning(
                "chat_state.push_event for unknown session %s — event dropped from log (kind=%s)",
                session_id,
                event.get("kind"),
            )
            return -1
        return state.push(event)

    def get_event_log(self, session_id: str) -> list[dict[str, Any]]:
        state = self._get_state(session_id)
        if state is None:
            return []
        return state.snapshot()

    def replay(self, session_id: str, last_seq: int) -> list[dict[str, Any]]:
        """Back-compat shim — returns just the events list. Callers that need
        to know whether a gap occurred should use ``replay_with_gap``."""
        return self.replay_with_gap(session_id, last_seq).events

    def replay_with_gap(self, session_id: str, last_seq: int) -> ReplayResult:
        state = self._get_state(session_id)
        if state is None:
            return ReplayResult(events=[], gap=False)
        return state.replay(last_seq)


class _SessionState:
    def __init__(self, *, max_events: int, start_seq: int = 0) -> None:
        self.log: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_events)
        self.seq: int = start_seq
        self._lock = threading.Lock()

    def push(self, event: dict[str, Any]) -> int:
        with self._lock:
            self.seq += 1
            tagged = {**event, "_seq": self.seq}
            self.log.append(tagged)
            return self.seq

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(e) for e in self.log]

    def replay(self, last_seq: int) -> ReplayResult:
        with self._lock:
            if not self.log:
                return ReplayResult(events=[], gap=False)
            oldest_seq = self.log[0]["_seq"]
            if last_seq < oldest_seq:
                events = [copy.deepcopy(e) for e in self.log]
                # Cursor predates the oldest retained seq — events between
                # last_seq and oldest_seq have been evicted.
                gap = last_seq > 0 and last_seq < oldest_seq - 1
                return ReplayResult(events=events, gap=gap)
            events = [copy.deepcopy(e) for e in self.log if e["_seq"] > last_seq]
            return ReplayResult(events=events, gap=False)
