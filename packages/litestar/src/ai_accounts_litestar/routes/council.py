"""Council route — a panel of role-agents debates a decision.

POST /api/v1/council → SSE stream of CouncilEvents ending in a
``decision`` (or ``council_error``) event. One-shot: no Last-Event-ID
reconnect/replay machinery (that exists for long-lived chat sessions;
a council run is a single finite deliberation).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

import msgspec
from ai_accounts_core.services.council import CouncilService
from litestar import Controller, post
from litestar.response import Stream

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 20.0


class _CouncilRequest(msgspec.Struct, kw_only=True):
    question: str
    # Every option and every round costs real LLM calls against real account
    # quotas — bound them at the API edge (the service clamps again).
    options: Annotated[list[str], msgspec.Meta(min_length=2, max_length=10)]
    context: str = ""
    rounds: Annotated[int, msgspec.Meta(ge=0, le=5)] = 1


def _format_sse(event_dict: dict[str, Any]) -> str:
    payload = msgspec.json.encode(event_dict).decode()
    return f"event: council\ndata: {payload}\n\n"


class CouncilController(Controller):
    path = "/api/v1/council"
    tags = ["council"]

    @post("/", status_code=200)
    async def convene(self, council: CouncilService, data: _CouncilRequest) -> Stream:
        gen = council.convene(
            question=data.question,
            options=data.options,
            context=data.context,
            rounds=data.rounds,
        )

        async def sse() -> AsyncIterator[str]:
            queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

            async def producer() -> None:
                try:
                    async for event in gen:
                        await queue.put(("event", event))
                except Exception as exc:
                    await queue.put(("error", exc))
                finally:
                    await queue.put(("done", None))

            producer_task = asyncio.create_task(producer())
            try:
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(
                            queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS
                        )
                    except TimeoutError:
                        yield f": heartbeat {int(time.time())}\n\n"
                        continue
                    if kind == "done":
                        break
                    if kind == "error":
                        logger.exception("council stream error", exc_info=payload)
                        msg = f"{type(payload).__name__}: {payload}" if str(payload) else "error"
                        yield _format_sse({"kind": "council_error", "error": msg})
                        continue
                    yield _format_sse(msgspec.to_builtins(payload))
            finally:
                producer_task.cancel()
                try:
                    await producer_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("council: producer cleanup raised")

        return Stream(
            sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
