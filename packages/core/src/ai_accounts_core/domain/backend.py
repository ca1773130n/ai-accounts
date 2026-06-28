from datetime import datetime
from enum import StrEnum

import msgspec


class BackendKind:
    """String constants for built-in backend kinds.

    Third-party backends may define their own kinds — `AccountService.create`
    accepts any string, validated against the set of registered backend impls.
    """

    CLAUDE = "claude"
    OPENCODE = "opencode"
    ANTIGRAVITY = "antigravity"
    CODEX = "codex"


class BackendStatus(StrEnum):
    UNCONFIGURED = "unconfigured"
    DETECTING = "detecting"
    NEEDS_LOGIN = "needs_login"
    NEEDS_REAUTH = "needs_reauth"
    VALIDATING = "validating"
    READY = "ready"
    ERROR = "error"


class Backend(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    kind: str
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
