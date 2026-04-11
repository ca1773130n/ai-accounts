from datetime import datetime
from enum import Enum

import msgspec


class BackendKind(str, Enum):
    CLAUDE = "claude"
    OPENCODE = "opencode"
    GEMINI = "gemini"
    CODEX = "codex"


class BackendStatus(str, Enum):
    UNCONFIGURED = "unconfigured"
    DETECTING = "detecting"
    NEEDS_LOGIN = "needs_login"
    VALIDATING = "validating"
    READY = "ready"
    ERROR = "error"


class Backend(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    kind: BackendKind
    display_name: str
    config: dict[str, object]
    status: BackendStatus
    created_at: datetime
    updated_at: datetime | None = None
    last_error: str | None = None


class BackendCredential(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    backend_id: str
    ciphertext: bytes
    key_id: str
    created_at: datetime
    expires_at: datetime | None = None


class DetectResult(msgspec.Struct, frozen=True, kw_only=True):
    installed: bool
    version: str | None = None
    path: str | None = None
    notes: str | None = None
