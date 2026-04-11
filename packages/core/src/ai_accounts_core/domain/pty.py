from datetime import datetime

import msgspec


class PtySession(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    backend_id: str
    command: tuple[str, ...]
    cols: int
    rows: int
    created_at: datetime
    ended_at: datetime | None = None
    exit_code: int | None = None


class PtyEvent(msgspec.Struct, frozen=True, kw_only=True):
    session_id: str
    kind: str  # "output" | "resize" | "exit" | "input"
    payload: bytes
    ts: datetime
