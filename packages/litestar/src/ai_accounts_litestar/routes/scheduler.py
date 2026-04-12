from __future__ import annotations

from litestar import Controller, get, post, put

from ai_accounts_core.domain.usage import FallbackChainEntry
from ai_accounts_core.services.scheduler import AccountScheduler


class SchedulerController(Controller):
    path = "/api/v1/scheduler"
    tags = ["scheduler"]

    @get("/health")
    async def get_all_health(self, scheduler: AccountScheduler) -> dict:
        health_list = await scheduler.get_all_health()
        return {"items": [_health_to_dict(h) for h in health_list]}

    @get("/health/{backend_id:str}")
    async def get_health(self, scheduler: AccountScheduler, backend_id: str) -> dict:
        health = await scheduler.get_health(backend_id)
        return _health_to_dict(health)

    @post("/pick", status_code=200)
    async def pick(self, scheduler: AccountScheduler, data: dict) -> dict:
        kind = data.get("kind")
        result = await scheduler.pick(kind=kind)
        if result is None:
            return {"backend_id": None, "kind": None, "retry_after": None}
        return {
            "backend_id": result.backend_id,
            "kind": result.kind,
            "isolation_dir": result.isolation_dir,
            "retry_after": None,
        }

    @get("/chain")
    async def get_chain(self, scheduler: AccountScheduler) -> dict:
        chain = await scheduler.get_chain()
        return {
            "entries": [
                {"backend_id": e.backend_id, "priority": e.priority}
                for e in chain
            ]
        }

    @put("/chain", status_code=200)
    async def set_chain(self, scheduler: AccountScheduler, data: dict) -> dict:
        entries = [
            FallbackChainEntry(backend_id=e["backend_id"], priority=e["priority"])
            for e in data.get("entries", [])
        ]
        await scheduler.set_chain(entries)
        return {"status": "ok"}

    @post("/mark-limited", status_code=204)
    async def mark_limited(self, scheduler: AccountScheduler, data: dict) -> None:
        await scheduler.mark_rate_limited(
            data["backend_id"],
            data["cooldown_seconds"],
            data["reason"],
        )


def _health_to_dict(health) -> dict:
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
            health.rate_limited_until.isoformat()
            if health.rate_limited_until
            else None
        ),
        "rate_limit_reason": health.rate_limit_reason,
        "last_used_at": (
            health.last_used_at.isoformat() if health.last_used_at else None
        ),
        "last_polled_at": (
            health.last_polled_at.isoformat() if health.last_polled_at else None
        ),
    }
