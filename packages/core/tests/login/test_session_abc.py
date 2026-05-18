import asyncio
from collections.abc import AsyncIterator

import pytest
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    PromptAnswer,
    TextPrompt,
)
from ai_accounts_core.login.session import LoginSession


class _Echo(LoginSession):
    def __init__(self) -> None:
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
        self._cancelled = False
        self._done = False

    @property
    def session_id(self) -> str:
        return "sess-echo"

    @property
    def backend_kind(self) -> str:
        return "fake"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="p-1", prompt="key")
        ans = await self._answers.get()
        assert ans.prompt_id == "p-1"
        yield LoginComplete(account_id="bkd-echo", backend_status="validating")
        self._done = True

    async def respond(self, answer: PromptAnswer) -> None:
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._cancelled = True
        self._done = True


@pytest.mark.asyncio
async def test_session_prompt_respond_complete():
    sess = _Echo()
    events: list[LoginEvent] = []

    async def consume() -> None:
        async for ev in sess.events():
            events.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the generator reach the prompt
    await sess.respond(PromptAnswer(prompt_id="p-1", answer="sk-test"))
    await task

    assert len(events) == 2
    assert isinstance(events[0], TextPrompt)
    assert isinstance(events[1], LoginComplete)
    assert sess.done is True


@pytest.mark.asyncio
async def test_session_cancel_sets_done():
    sess = _Echo()
    await sess.cancel()
    assert sess.done is True


@pytest.mark.asyncio
async def test_session_cancel_during_consumption():
    sess = _Echo()
    started = asyncio.Event()

    async def consume() -> list[LoginEvent]:
        out: list[LoginEvent] = []
        async for ev in sess.events():
            out.append(ev)
            started.set()
            # blocks on next iteration waiting for respond()
        return out

    task = asyncio.create_task(consume())
    await started.wait()
    await sess.cancel()
    # Cancel does not inject an event; consumer task will hang waiting for
    # the answer queue. Close by cancelling the task.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sess.done is True
