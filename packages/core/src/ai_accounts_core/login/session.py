"""LoginSession — abstract base for interactive backend login flows.

One session per backend login attempt. The caller:
  1. iterates .events() to get URL prompts, text prompts, stdout, complete/failed
  2. calls .respond(answer) to satisfy text prompts
  3. calls .cancel() to abort

Implementations own their subprocess / HTTP resources and must be idempotent
on cancel.

Late-subscriber replay
----------------------
When an SSE client reconnects mid-flow (page refresh, network blip, tab
reopen), the new subscription otherwise only sees events emitted AFTER
reconnect. If the OAuth ``UrlPrompt`` was emitted before the reconnect,
the user would be stuck on a spinner forever.

To fix this, :meth:`events_with_replay` wraps the subclass's ``events()``
iterator and caches the most recent :class:`UrlPrompt` into
``_last_url_prompt``. SSE route handlers should call
``events_with_replay()`` (not ``events()`` directly) AND yield the
cached prompt to new subscribers before entering the live loop.

This only fixes reconnect-within-session — the underlying ``events()``
iterator is still single-consumer. Multi-subscriber broadcast is a
separate architectural concern.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ai_accounts_core.login.events import LoginEvent, PromptAnswer, UrlPrompt


class LoginSession(ABC):
    # Cached last-emitted UrlPrompt for late SSE subscribers. Set by
    # ``_capture_for_replay`` on every emitted event. Declared on the ABC
    # so all subclasses get it for free without touching their __init__.
    # Instance assignment (in ``_capture_for_replay``) shadows this
    # class-level default, so the None sentinel isn't shared across
    # instances in practice.
    _last_url_prompt: UrlPrompt | None = None

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

    @property
    def last_url_prompt(self) -> UrlPrompt | None:
        """Most recently emitted UrlPrompt, or None if none has fired.

        Read-only view used by SSE route handlers to replay the OAuth
        URL to reconnecting subscribers.
        """
        return self._last_url_prompt

    def _capture_for_replay(self, event: LoginEvent) -> None:
        """Cache an event for replay to late subscribers.

        Currently only :class:`UrlPrompt` is cached — the OAuth URL is
        the one thing a spinning client cannot recover from missing.
        Other event types (progress, stdout) are either transient or
        re-emitted naturally.
        """
        if isinstance(event, UrlPrompt):
            self._last_url_prompt = event

    async def events_with_replay(self) -> AsyncIterator[LoginEvent]:
        """Like :meth:`events` but captures each event for late-subscriber replay.

        Route handlers should prefer this over ``events()`` so that
        ``last_url_prompt`` is populated without every backend subclass
        needing to call ``_capture_for_replay`` manually.
        """
        async for event in self.events():
            self._capture_for_replay(event)
            yield event

    @abstractmethod
    async def events(self) -> AsyncIterator[LoginEvent]:
        """Yield login events until the flow completes or fails."""
        if False:
            yield  # pragma: no cover  # makes the abstract body an async generator

    @abstractmethod
    async def respond(self, answer: PromptAnswer) -> None: ...

    @abstractmethod
    async def cancel(self) -> None: ...
