"""Tests for late-subscriber UrlPrompt replay in LoginSession.

When an SSE client reconnects mid-login (page refresh, network blip,
tab reopen), the new subscription must not lose the OAuth URL that was
emitted before the reconnect. LoginSession caches the last UrlPrompt
during ``events_with_replay()`` so the route handler can re-emit it.

See ``packages/core/src/ai_accounts_core/login/session.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    PromptAnswer,
    ProgressUpdate,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)
from ai_accounts_core.login.session import LoginSession


class _ScriptedSession(LoginSession):
    """Minimal LoginSession that emits a pre-scripted event sequence."""

    def __init__(self, script: list[LoginEvent]) -> None:
        self._script = list(script)
        self._done = False

    @property
    def session_id(self) -> str:
        return "sess-scripted"

    @property
    def backend_kind(self) -> str:
        return "fake"

    @property
    def flow_kind(self) -> str:
        return "oauth_device"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        for ev in self._script:
            yield ev
        self._done = True

    async def respond(self, answer: PromptAnswer) -> None:  # pragma: no cover
        return None

    async def cancel(self) -> None:
        self._done = True


@pytest.mark.asyncio
async def test_session_caches_last_url_prompt() -> None:
    """events_with_replay() populates last_url_prompt as events pass through."""
    url = UrlPrompt(prompt_id="p-1", url="https://example.com/oauth", user_code="ABC-123")
    sess = _ScriptedSession([
        ProgressUpdate(label="starting"),
        url,
        LoginComplete(account_id="bkd-x", backend_status="validating"),
    ])

    # Before iteration: nothing cached.
    assert sess.last_url_prompt is None

    seen: list[LoginEvent] = []
    async for ev in sess.events_with_replay():
        seen.append(ev)
        if isinstance(ev, UrlPrompt):
            # As soon as the URL is observed, the cache must reflect it.
            assert sess.last_url_prompt is ev

    assert sess.last_url_prompt is url
    assert sess.last_url_prompt is not None
    assert sess.last_url_prompt.url == "https://example.com/oauth"
    assert sess.last_url_prompt.user_code == "ABC-123"
    # All three events flowed through unchanged.
    assert len(seen) == 3


@pytest.mark.asyncio
async def test_session_no_url_prompt_cached_if_none_emitted() -> None:
    """A flow that never emits UrlPrompt leaves the cache empty."""
    sess = _ScriptedSession([
        TextPrompt(prompt_id="p-1", prompt="API key:", hidden=True),
        StdoutChunk(text="signing you in..."),
        LoginComplete(account_id="bkd-x", backend_status="validating"),
    ])

    async for _ev in sess.events_with_replay():
        pass

    assert sess.last_url_prompt is None


@pytest.mark.asyncio
async def test_session_keeps_most_recent_url_prompt() -> None:
    """If multiple UrlPrompts are emitted, the latest wins."""
    u1 = UrlPrompt(prompt_id="p-1", url="https://example.com/first")
    u2 = UrlPrompt(prompt_id="p-2", url="https://example.com/second")
    sess = _ScriptedSession([
        u1,
        StdoutChunk(text="retrying..."),
        u2,
        LoginFailed(code="cancelled", message="user cancelled"),
    ])

    async for _ev in sess.events_with_replay():
        pass

    assert sess.last_url_prompt is u2


@pytest.mark.asyncio
async def test_raw_events_does_not_populate_cache() -> None:
    """Callers that use the raw events() iterator do NOT trigger replay caching.

    This is a guardrail: the cache is a contract of events_with_replay().
    If subclasses want auto-capture, they must route through the wrapper.
    """
    url = UrlPrompt(prompt_id="p-1", url="https://example.com/raw")
    sess = _ScriptedSession([
        url,
        LoginComplete(account_id="bkd-x", backend_status="validating"),
    ])

    async for _ev in sess.events():
        pass

    # Raw iteration doesn't populate the cache.
    assert sess.last_url_prompt is None


@pytest.mark.asyncio
async def test_cache_visible_to_concurrent_reader() -> None:
    """Mid-flow: a second coroutine can read the cache after the URL fires."""
    url = UrlPrompt(prompt_id="p-1", url="https://example.com/mid")
    sess = _ScriptedSession([
        ProgressUpdate(label="starting"),
        url,
        # Block the iterator so we can inspect cache state from outside.
        StdoutChunk(text="waiting for callback..."),
        LoginComplete(account_id="bkd-x", backend_status="validating"),
    ])

    url_seen = asyncio.Event()

    async def consume() -> None:
        async for ev in sess.events_with_replay():
            if isinstance(ev, UrlPrompt):
                url_seen.set()

    task = asyncio.create_task(consume())
    await url_seen.wait()
    # Cache must be visible to a different coroutine at this point.
    assert sess.last_url_prompt is url
    await task
    assert sess.last_url_prompt is url
