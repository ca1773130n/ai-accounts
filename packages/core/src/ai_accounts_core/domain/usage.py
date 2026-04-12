from datetime import datetime

import msgspec


class UsageWindow(msgspec.Struct, frozen=True, kw_only=True):
    window_type: str
    usage_percent: float
    resets_at: datetime | None
    tokens_used: int | None = None
    tokens_limit: int | None = None


class AccountHealth(msgspec.Struct, frozen=True, kw_only=True):
    backend_id: str
    kind: str
    windows: tuple[UsageWindow, ...]
    rate_limited_until: datetime | None = None
    rate_limit_reason: str | None = None
    last_used_at: datetime | None = None
    last_polled_at: datetime | None = None


class FallbackChainEntry(msgspec.Struct, frozen=True, kw_only=True):
    backend_id: str
    priority: int


class PickResult(msgspec.Struct, frozen=True, kw_only=True):
    backend_id: str
    kind: str
    credential: bytes
    isolation_dir: str
    retry_after: datetime | None = None
