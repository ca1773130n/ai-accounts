from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from ai_accounts_core.domain.chat import ChatDelta
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.scheduler import AccountScheduler

logger = logging.getLogger(__name__)


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
