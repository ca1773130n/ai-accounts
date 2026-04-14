from __future__ import annotations

import collections
import threading
from typing import Any


class ChatStateService:
    """Seq-numbered event log with cursor-based replay for SSE reconnection."""

    def __init__(self, *, max_events: int = 1000) -> None:
        self._max_events = max_events
        self._sessions: dict[str, _SessionState] = {}
        self._lock = threading.Lock()

    def init_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions[session_id] = _SessionState(max_events=self._max_events)

    def remove_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def push_event(self, session_id: str, event: dict[str, Any]) -> int:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return -1
            return state.push(event)

    def get_event_log(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return []
            return list(state.log)

    def replay(self, session_id: str, last_seq: int) -> list[dict[str, Any]]:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return []
            if not state.log:
                return []
            oldest_seq = state.log[0]["_seq"]
            if last_seq < oldest_seq:
                return list(state.log)
            return [e for e in state.log if e["_seq"] > last_seq]


class _SessionState:
    def __init__(self, *, max_events: int) -> None:
        self.log: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_events)
        self.seq: int = 0

    def push(self, event: dict[str, Any]) -> int:
        self.seq += 1
        tagged = {**event, "_seq": self.seq}
        self.log.append(tagged)
        return self.seq
