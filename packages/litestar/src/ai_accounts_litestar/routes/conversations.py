"""Conversation routes — CRUD + SSE streaming."""

from __future__ import annotations

import msgspec
from litestar import Controller, get, post
from litestar.response import Stream
from litestar.status_codes import HTTP_201_CREATED

from ai_accounts_core.services.chat import ChatService


class _CreateSessionRequest(msgspec.Struct, kw_only=True):
    backend_id: str
    model: str
    title: str | None = None


class _SendMessageRequest(msgspec.Struct, kw_only=True):
    content: str


class ConversationsController(Controller):
    path = "/api/v1/conversations"
    tags = ["conversations"]

    @post("/", status_code=HTTP_201_CREATED)
    async def create_session(
        self, chat_service: ChatService, data: _CreateSessionRequest
    ) -> dict:
        session = await chat_service.create_session(
            backend_id=data.backend_id,
            model=data.model,
            title=data.title,
        )
        return {
            "id": session.id,
            "backend_id": session.backend_id,
            "model": session.model,
            "title": session.title,
            "created_at": session.created_at.isoformat(),
        }

    @get("/")
    async def list_sessions(
        self, chat_service: ChatService, backend_id: str | None = None
    ) -> dict:
        sessions = await chat_service.list_sessions(backend_id=backend_id)
        return {
            "items": [
                {
                    "id": s.id,
                    "backend_id": s.backend_id,
                    "model": s.model,
                    "title": s.title,
                    "created_at": s.created_at.isoformat(),
                }
                for s in sessions
            ]
        }

    @get("/{session_id:str}")
    async def get_session(
        self, chat_service: ChatService, session_id: str
    ) -> dict:
        session = await chat_service.get_session(session_id)
        messages = await chat_service.get_messages(session_id)
        return {
            "id": session.id,
            "backend_id": session.backend_id,
            "model": session.model,
            "title": session.title,
            "created_at": session.created_at.isoformat(),
            "messages": [
                {
                    "id": m.id,
                    "role": m.role.value,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                    "model": m.model,
                    "tokens_in": m.tokens_in,
                    "tokens_out": m.tokens_out,
                }
                for m in messages
            ],
        }

    @post("/{session_id:str}/messages", status_code=200)
    async def send_message(
        self,
        chat_service: ChatService,
        session_id: str,
        data: _SendMessageRequest,
    ) -> Stream:
        async def generate():
            async for delta in chat_service.send_message(
                session_id=session_id, content=data.content
            ):
                payload = msgspec.json.encode(delta).decode()
                yield f"event: chat\ndata: {payload}\n\n"

        return Stream(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
