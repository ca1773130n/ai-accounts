from __future__ import annotations

import logging

import msgspec
from litestar import Controller, post
from litestar.response import Stream

from ai_accounts_core.services.chat_orchestrator import ChatOrchestrator

logger = logging.getLogger(__name__)


class _SendRequest(msgspec.Struct, kw_only=True):
    session_id: str
    content: str
    mode: str = "single"
    backend_kind: str | None = None
    account_id: str | None = None
    model: str | None = None


class ChatSendController(Controller):
    path = "/api/v1/chat"
    tags = ["chat"]

    @post("/send", status_code=200)
    async def send(
        self, orchestrator: ChatOrchestrator, data: _SendRequest
    ) -> Stream:
        if data.mode == "all":
            gen = orchestrator.send_all(
                session_id=data.session_id, content=data.content
            )
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

        async def sse():
            try:
                async for event in gen:
                    payload = msgspec.json.encode(event).decode()
                    yield f"event: chat\ndata: {payload}\n\n"
            except Exception as exc:
                logger.exception(
                    "chat send stream error: session=%s mode=%s",
                    data.session_id, data.mode,
                )
                msg = f"{type(exc).__name__}: {exc}" if str(exc) else "Stream error"
                error_payload = msgspec.json.encode(
                    {"kind": "error", "payload": msg}
                ).decode()
                yield f"event: chat\ndata: {error_payload}\n\n"

        return Stream(
            sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
