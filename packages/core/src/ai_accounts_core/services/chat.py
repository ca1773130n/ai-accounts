from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from ai_accounts_core.domain.chat import ChatDelta, ChatMessage, ChatRole, ChatSession
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.backend import ChatRequest
from ai_accounts_core.protocols.storage import StorageProtocol
from ai_accounts_core.services.accounts import AccountService

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class ChatService:
    def __init__(self, *, account_service: AccountService, storage: StorageProtocol) -> None:
        self._account_service = account_service
        self._storage = storage

    async def create_session(
        self, *, backend_id: str, model: str, title: str | None = None
    ) -> ChatSession:
        await self._account_service.get(backend_id)
        session = ChatSession(
            id=new_id("cht"), backend_id=backend_id, title=title, created_at=_now(), model=model
        )
        history = await self._storage.history()
        await history.create_session(session)
        return session

    async def get_session(self, session_id: str) -> ChatSession:
        history = await self._storage.history()
        sessions = await history.list_sessions()
        for s in sessions:
            if s.id == session_id:
                return s
        raise KeyError(f"chat session not found: {session_id}")

    async def list_sessions(self, *, backend_id: str | None = None) -> list[ChatSession]:
        history = await self._storage.history()
        return await history.list_sessions(backend_id=backend_id)

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        await self.get_session(session_id)
        history = await self._storage.history()
        return await history.list_messages(session_id)

    async def append_message(self, message: ChatMessage) -> None:
        history = await self._storage.history()
        await history.append_message(message)

    async def delete_session(self, session_id: str) -> bool:
        """Discard a session and its messages. True if one existed.

        For callers using this service as a one-shot completion api rather than
        a conversation: create, send, read the answer, delete. Without it every
        such call leaves a session and its messages behind for ever, since
        nothing else in this package can remove them.

        Deliberately no `get_session` check first — that would cost a full
        `list_sessions` scan to decide whether to issue a DELETE that is
        already idempotent, and would turn a cleanup in a `finally` block into
        something that can raise while another exception is in flight.
        """
        history = await self._storage.history()
        return await history.delete_session(session_id)

    async def send_message(
        self,
        *,
        session_id: str,
        content: str,
        role: ChatRole = ChatRole.USER,
    ) -> AsyncIterator[ChatDelta]:
        session = await self.get_session(session_id)
        backend = await self._account_service.get(session.backend_id)
        impl = self._account_service._impl_for(backend.kind)

        # Persist user message
        user_msg = ChatMessage(
            id=new_id("msg"),
            session_id=session_id,
            role=role,
            content=content,
            created_at=_now(),
        )
        await self.append_message(user_msg)

        # Build context from history
        history_msgs = await self.get_messages(session_id)

        # Get credential
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend.id)
        if stored is None:
            from ai_accounts_core.services.errors import CredentialMissing

            raise CredentialMissing(backend.id)
        plaintext = await self._account_service._vault.decrypt(
            stored.ciphertext, context={"backend_id": backend.id}
        )

        request = ChatRequest(messages=tuple(history_msgs), model=session.model or "default")
        isolation_dir = self._account_service._isolation_dir(backend.id)

        # Stream response
        accumulated_text = ""
        tokens_in = None
        tokens_out = None
        model_used = None
        async for event in impl.chat(request, plaintext, isolation_dir=isolation_dir):
            if event.kind == "tool_call" and isinstance(event.payload, dict):
                delta = ChatDelta(
                    kind="tool_call",
                    tool_id=event.payload.get("id"),
                    tool_name=event.payload.get("name"),
                    tool_arguments=event.payload.get("arguments"),
                )
                yield delta
                continue
            delta = ChatDelta(
                kind=event.kind,
                payload=event.payload if isinstance(event.payload, str) else None,
                tokens_in=event.payload.get("tokens_in")
                if isinstance(event.payload, dict)
                else None,
                tokens_out=event.payload.get("tokens_out")
                if isinstance(event.payload, dict)
                else None,
                model=event.payload.get("model") if isinstance(event.payload, dict) else None,
                finish_reason=event.payload.get("finish_reason")
                if isinstance(event.payload, dict)
                else None,
            )
            if delta.kind == "token" and delta.payload:
                accumulated_text += delta.payload
            if delta.tokens_in is not None:
                tokens_in = delta.tokens_in
            if delta.tokens_out is not None:
                tokens_out = delta.tokens_out
            if delta.model:
                model_used = delta.model
            yield delta

        # Persist assistant response
        if accumulated_text:
            assistant_msg = ChatMessage(
                id=new_id("msg"),
                session_id=session_id,
                role=ChatRole.ASSISTANT,
                content=accumulated_text,
                created_at=_now(),
                model=model_used or session.model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            await self.append_message(assistant_msg)
