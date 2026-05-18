"""Conversation routes — CRUD + SSE streaming."""

from __future__ import annotations

import logging
from typing import Annotated

import msgspec
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.errors import CredentialMissing, ServiceError
from litestar import Controller, get, post
from litestar.exceptions import HTTPException, NotFoundException
from litestar.response import Stream
from litestar.status_codes import HTTP_201_CREATED

logger = logging.getLogger(__name__)

# Size caps bound request memory and downstream-backend payloads. Numbers are
# generous enough for real prompts but stop accidental/DoS-shaped inputs.
_BACKEND_ID_MAX = 128
_MODEL_MAX = 256
_TITLE_MAX = 256
_CONTENT_MAX = 1_000_000  # ~1 MB of text


class _CreateSessionRequest(msgspec.Struct, kw_only=True):
    backend_id: Annotated[str, msgspec.Meta(min_length=1, max_length=_BACKEND_ID_MAX)]
    model: Annotated[str, msgspec.Meta(min_length=1, max_length=_MODEL_MAX)]
    title: Annotated[str, msgspec.Meta(max_length=_TITLE_MAX)] | None = None


class _SendMessageRequest(msgspec.Struct, kw_only=True):
    content: Annotated[str, msgspec.Meta(min_length=1, max_length=_CONTENT_MAX)]


def _session_not_found(session_id: str) -> NotFoundException:
    return NotFoundException(detail=f"chat session not found: {session_id}")


class ConversationsController(Controller):
    path = "/api/v1/conversations"
    tags = ["conversations"]

    @post("/", status_code=HTTP_201_CREATED)
    async def create_session(self, chat_service: ChatService, data: _CreateSessionRequest) -> dict:
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
    async def list_sessions(self, chat_service: ChatService, backend_id: str | None = None) -> dict:
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
    async def get_session(self, chat_service: ChatService, session_id: str) -> dict:
        try:
            session = await chat_service.get_session(session_id)
        except KeyError:
            raise _session_not_found(session_id) from None
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
        # Preflight: fail fast with a proper HTTP status before we open the
        # stream. Otherwise an unknown session / missing credential would
        # surface as an abrupt connection close mid-stream after 200 OK.
        try:
            await chat_service.get_session(session_id)
        except KeyError:
            raise _session_not_found(session_id) from None
        except ServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        async def generate():
            try:
                async for delta in chat_service.send_message(
                    session_id=session_id, content=data.content
                ):
                    payload = msgspec.json.encode(delta).decode()
                    yield f"event: chat\ndata: {payload}\n\n"
            except (KeyError, CredentialMissing, ServiceError) as exc:
                logger.exception("conversations.send_message stream error: session=%s", session_id)
                err = {"kind": "error", "payload": f"{type(exc).__name__}: {exc}"}
                yield f"event: chat\ndata: {msgspec.json.encode(err).decode()}\n\n"
            except Exception as exc:
                logger.exception(
                    "conversations.send_message unexpected error: session=%s",
                    session_id,
                )
                err = {"kind": "error", "payload": f"{type(exc).__name__}: {exc}"}
                yield f"event: chat\ndata: {msgspec.json.encode(err).decode()}\n\n"

        return Stream(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
