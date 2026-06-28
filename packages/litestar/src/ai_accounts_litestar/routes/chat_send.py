from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import msgspec
from ai_accounts_core.services.chat_orchestrator import ChatOrchestrator
from ai_accounts_core.services.chat_state import ChatStateService
from litestar import Controller, Request, post
from litestar.response import Stream

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 20.0


class _SendRequest(msgspec.Struct, kw_only=True):
    session_id: str
    content: str
    mode: str = "single"
    backend_kind: str | None = None
    account_id: str | None = None
    model: str | None = None


def _parse_last_event_id(raw: str | None) -> int:
    if not raw:
        return 0
    stripped = raw.strip()
    if stripped.isdigit():
        return int(stripped)
    logger.warning(
        "chat_send: malformed Last-Event-ID header %r — treating as fresh connection", raw
    )
    return 0


def _format_sse(event_dict: dict[str, Any], seq: int | None) -> str:
    payload = msgspec.json.encode(event_dict).decode()
    if seq is not None and seq > 0:
        return f"id: {seq}\nevent: chat\ndata: {payload}\n\n"
    return f"event: chat\ndata: {payload}\n\n"


class ChatSendController(Controller):
    path = "/api/v1/chat"
    tags = ["chat"]

    @post("/send", status_code=200)
    async def send(
        self,
        orchestrator: ChatOrchestrator,
        chat_state: ChatStateService,
        data: _SendRequest,
        request: Request[Any, Any, Any],
    ) -> Stream:
        last_event_id = _parse_last_event_id(request.headers.get("last-event-id"))

        # gen is one of three differently-typed async iterators depending on
        # mode; widen to a common type so the branch assignments unify.
        gen: AsyncIterator[Any]
        if data.mode == "all":
            gen = orchestrator.send_all(session_id=data.session_id, content=data.content)
        elif data.mode == "compound":
            gen = orchestrator.send_compound(
                session_id=data.session_id,
                content=data.content,
                primary_kind=data.backend_kind,
            )
        else:
            gen = orchestrator.send_single(
                session_id=data.session_id,
                content=data.content,
                backend_kind=data.backend_kind,
                account_id=data.account_id,
                model=data.model,
            )

        async def sse() -> AsyncIterator[str]:
            session_id = data.session_id
            # Reconnect: replay retained events first, then ensure session
            # exists for new events. If the session was evicted server-side
            # since the client's last_event_id, seed the seq counter from
            # last_event_id so fresh events keep a monotonic id — otherwise
            # the client's dedup would silently drop them.
            if last_event_id > 0:
                result = chat_state.replay_with_gap(session_id, last_event_id)
                if result.gap:
                    # Events between the client's cursor and what we retained
                    # have been evicted. Emit an explicit gap marker so the
                    # client can re-sync rather than silently miss history.
                    gap_event = {
                        "kind": "gap",
                        "payload": {
                            "last_seen_seq": last_event_id,
                            "next_seq": result.events[0]["_seq"] if result.events else None,
                        },
                    }
                    yield _format_sse(gap_event, None)
                for ev in result.events:
                    yield _format_sse(ev, ev.get("_seq"))
                if not chat_state.get_event_log(session_id):
                    logger.info(
                        "chat_send: session %s had no retained log at reconnect (last_event_id=%d); seeding seq",
                        session_id,
                        last_event_id,
                    )
                    chat_state.init_session(session_id, start_seq=last_event_id)
            else:
                chat_state.init_session(session_id)

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
                        # heartbeat comment — best effort
                        yield f": heartbeat {int(time.time())}\n\n"
                        continue

                    if kind == "done":
                        break
                    if kind == "error":
                        exc = payload
                        logger.exception(
                            "chat send stream error: session=%s mode=%s",
                            data.session_id,
                            data.mode,
                            exc_info=exc,
                        )
                        msg = f"{type(exc).__name__}: {exc}" if str(exc) else "Stream error"
                        error_event = {"kind": "error", "payload": msg}
                        seq = chat_state.push_event(session_id, error_event)
                        tagged = {**error_event, "_seq": seq} if seq > 0 else error_event
                        yield _format_sse(tagged, seq if seq > 0 else None)
                        continue

                    # kind == "event"
                    event = payload
                    event_dict = event if isinstance(event, dict) else msgspec.to_builtins(event)
                    seq = chat_state.push_event(session_id, event_dict)
                    tagged = {**event_dict, "_seq": seq} if seq > 0 else event_dict
                    yield _format_sse(tagged, seq if seq > 0 else None)
            finally:
                producer_task.cancel()
                try:
                    await producer_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception(
                        "chat_send: producer cleanup raised for session=%s mode=%s",
                        data.session_id,
                        data.mode,
                    )
                chat_state.remove_session(session_id)

        return Stream(
            sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
