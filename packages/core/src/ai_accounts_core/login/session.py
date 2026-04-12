"""LoginSession — abstract base for interactive backend login flows.

One session per backend login attempt. The caller:
  1. iterates .events() to get URL prompts, text prompts, stdout, complete/failed
  2. calls .respond(answer) to satisfy text prompts
  3. calls .cancel() to abort

Implementations own their subprocess / HTTP resources and must be idempotent
on cancel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ai_accounts_core.login.events import LoginEvent, PromptAnswer


class LoginSession(ABC):
    @property
    @abstractmethod
    def session_id(self) -> str: ...

    @property
    @abstractmethod
    def backend_kind(self) -> str: ...

    @property
    @abstractmethod
    def flow_kind(self) -> str: ...

    @property
    @abstractmethod
    def done(self) -> bool: ...

    @property
    def credential(self) -> bytes | None:
        """Credential obtained during login, if any.

        For API key flows, this is the key bytes.
        For CLI-browser/OAuth flows, this is None (the CLI wrote the
        token to its config directory — validate() uses the config dir).
        Read after LoginComplete is emitted.
        """
        return None

    @abstractmethod
    async def events(self) -> AsyncIterator[LoginEvent]:
        """Yield login events until the flow completes or fails."""
        if False:
            yield  # pragma: no cover  # makes the abstract body an async generator

    @abstractmethod
    async def respond(self, answer: PromptAnswer) -> None: ...

    @abstractmethod
    async def cancel(self) -> None: ...
