from datetime import datetime
from enum import Enum

import msgspec


class SessionKind(str, Enum):
    CHAT = "chat"
    PTY = "pty"


class SessionState(str, Enum):
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
