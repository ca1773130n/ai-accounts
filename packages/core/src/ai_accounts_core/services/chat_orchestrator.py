from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from ai_accounts_core.domain.chat import ChatDelta, ChatMessage, ChatRole
from ai_accounts_core.domain.chat_events import AllModeEvent
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.backend import ChatRequest
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.scheduler import AccountScheduler

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class ChatOrchestrator:
    def __init__(self, *, chat_service: ChatService, scheduler: AccountScheduler) -> None:
        self._chat = chat_service
        self._scheduler = scheduler

    async def send_single(
        self,
        *,
        session_id: str,
        content: str,
        backend_kind: str | None = None,
        account_id: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[ChatDelta]:
        """Single mode: use ChatService.send_message which already handles credentials."""
        async for event in self._chat.send_message(session_id=session_id, content=content):
            yield event

    # ── All-mode: parallel fan-out ──

    async def send_all(
        self,
        *,
        session_id: str,
        content: str,
    ) -> AsyncIterator[AllModeEvent]:
        """Fan out to every READY backend in parallel, merging events via a queue."""
        # Persist user message
        user_msg = ChatMessage(
            id=new_id("msg"),
            session_id=session_id,
            role=ChatRole.USER,
            content=content,
            created_at=_now(),
        )
        await self._chat.append_message(user_msg)

        # Build context from history
        history = await self._chat.get_messages(session_id)

        health_list = await self._scheduler.get_all_health()
        ready = list(health_list)
        if not ready:
            yield AllModeEvent(kind="backend_error", backend="none", error="No backends available")
            return

        queue: asyncio.Queue[AllModeEvent | None] = asyncio.Queue()
        tasks: list[asyncio.Task[None]] = []

        async def _call_one(health) -> None:  # noqa: ANN001
            try:
                result = await self._scheduler.pick(kind=health.kind)
                if not result:
                    await queue.put(
                        AllModeEvent(kind="backend_error", backend=health.kind, error="no account available"),
                    )
                    return
                impl = self._scheduler._accounts._impl_for(health.kind)
                request = ChatRequest(messages=tuple(history), model="auto")
                async for event in impl.chat(
                    request, result.credential, isolation_dir=Path(result.isolation_dir),
                ):
                    if event.kind == "token" and isinstance(event.payload, str):
                        await queue.put(
                            AllModeEvent(kind="backend_delta", backend=health.kind, text=event.payload),
                        )
                    elif event.kind == "error":
                        await queue.put(
                            AllModeEvent(kind="backend_error", backend=health.kind, error=str(event.payload)),
                        )
                await queue.put(AllModeEvent(kind="backend_complete", backend=health.kind))
            except asyncio.TimeoutError:
                await queue.put(AllModeEvent(kind="backend_timeout", backend=health.kind))
            except Exception as exc:
                await queue.put(AllModeEvent(kind="backend_error", backend=health.kind, error=str(exc)))

        for h in ready:
            task = asyncio.create_task(asyncio.wait_for(_call_one(h), timeout=30.0))
            tasks.append(task)

        async def _monitor() -> None:
            for t in tasks:
                try:
                    await t
                except Exception:
                    pass  # errors already sent to queue
            await queue.put(None)  # sentinel

        monitor_task = asyncio.create_task(_monitor())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        await monitor_task
