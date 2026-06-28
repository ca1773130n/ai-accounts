from datetime import datetime
from enum import StrEnum

import msgspec


class SessionKind(StrEnum):
    CHAT = "chat"
    PTY = "pty"


class SessionState(StrEnum):
    STARTING = "starting"
    ACTIVE = "active"
    DISCONNECTED = "disconnected"
    ENDED = "ended"
    ERRORED = "errored"


class LiveSession(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    kind: SessionKind
    backend_id: str
    state: SessionState
    started_at: datetime
    last_seen_at: datetime
