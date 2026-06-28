from __future__ import annotations

from typing import Any

import msgspec
from ai_accounts_core.domain.usage import FallbackChainEntry
from ai_accounts_core.services.scheduler import AccountScheduler
from litestar import Controller, Response, get, post, put


class _PickRequest(msgspec.Struct, kw_only=True):
    kind: str | None = None


class _ChainEntryInput(msgspec.Struct, kw_only=True):
    backend_id: str
    priority: int


class _SetChainRequest(msgspec.Struct, kw_only=True):
    entries: list[_ChainEntryInput]


class _MarkLimitedRequest(msgspec.Struct, kw_only=True):
    backend_id: str
    cooldown_seconds: int
    reason: str


class SchedulerController(Controller):
    path = "/api/v1/scheduler"
    tags = ["scheduler"]

    @get("/health")
    async def get_all_health(self, scheduler: AccountScheduler) -> dict[str, object]:
        health_list = await scheduler.get_all_health()
        return {"items": [_health_to_dict(h) for h in health_list]}

    @get("/health/{backend_id:str}")
    async def get_health(self, scheduler: AccountScheduler, backend_id: str) -> dict[str, object]:
        health = await scheduler.get_health(backend_id)
        return _health_to_dict(health)

    @post("/pick", status_code=200)
    async def pick(
        self, scheduler: AccountScheduler, data: _PickRequest
    ) -> Response[Any] | dict[str, object]:
        result = await scheduler.pick(kind=data.kind)
        if result is None:
            return Response(content=None, status_code=204)
        return {
            "backend_id": result.backend_id,
            "kind": result.kind,
            "isolation_dir": result.isolation_dir,
            "retry_after": (result.retry_after.isoformat() if result.retry_after else None),
        }

    @get("/chain")
    async def get_chain(self, scheduler: AccountScheduler) -> dict[str, object]:
        chain = await scheduler.get_chain()
        return {"entries": [{"backend_id": e.backend_id, "priority": e.priority} for e in chain]}

    @put("/chain", status_code=200)
    async def set_chain(
        self, scheduler: AccountScheduler, data: _SetChainRequest
    ) -> dict[str, object]:
        entries = [
            FallbackChainEntry(backend_id=e.backend_id, priority=e.priority) for e in data.entries
        ]
        await scheduler.set_chain(entries)
        return {"status": "ok"}

    @post("/mark-limited", status_code=204)
    async def mark_limited(self, scheduler: AccountScheduler, data: _MarkLimitedRequest) -> None:
        await scheduler.mark_rate_limited(
            data.backend_id,
            data.cooldown_seconds,
            data.reason,
        )


def _health_to_dict(health: Any) -> dict[str, object]:
    return {
        "backend_id": health.backend_id,
        "kind": health.kind,
        "windows": [
            {
                "window_type": w.window_type,
                "usage_percent": w.usage_percent,
                "resets_at": w.resets_at.isoformat() if w.resets_at else None,
                "tokens_used": w.tokens_used,
                "tokens_limit": w.tokens_limit,
            }
            for w in health.windows
        ],
        "rate_limited_until": (
            health.rate_limited_until.isoformat() if health.rate_limited_until else None
        ),
        "rate_limit_reason": health.rate_limit_reason,
        "last_used_at": (health.last_used_at.isoformat() if health.last_used_at else None),
        "last_polled_at": (health.last_polled_at.isoformat() if health.last_polled_at else None),
    }
