import asyncio
from collections.abc import AsyncIterator

import pytest

from ai_accounts_core.login.events import LoginComplete, LoginEvent, PromptAnswer
from ai_accounts_core.login.registry import LoginSessionRegistry
from ai_accounts_core.login.session import LoginSession


class _Stub(LoginSession):
    def __init__(self, sid: str) -> None:
        self._sid = sid
        self._done = False

    @property
    def session_id(self) -> str: return self._sid
    @property
    def backend_kind(self) -> str: return "fake"
    @property
    def flow_kind(self) -> str: return "api_key"
    @property
    def done(self) -> bool: return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield LoginComplete(account_id="bkd-x", backend_status="validating")
        self._done = True

    async def respond(self, answer: PromptAnswer) -> None: ...
    async def cancel(self) -> None: self._done = True


@pytest.mark.asyncio
async def test_register_and_get():
    reg = LoginSessionRegistry(ttl_seconds=60)
    s = _Stub("sess-1")
    await reg.register(s, backend_id="bkd-1")
    assert await reg.get("sess-1") is s
    assert await reg.get("sess-1", backend_id="bkd-1") is s
    # Wrong backend_id returns None (looks like not-found to attackers
    # probing across backends).
    assert await reg.get("sess-1", backend_id="bkd-other") is None
    assert await reg.backend_id_for("sess-1") == "bkd-1"


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    reg = LoginSessionRegistry(ttl_seconds=60)
    assert await reg.get("nope") is None


@pytest.mark.asyncio
async def test_expired_session_purged():
    reg = LoginSessionRegistry(ttl_seconds=0)
    await reg.register(_Stub("sess-2"), backend_id="bkd-1")
    await asyncio.sleep(0.01)
    await reg.sweep()
    assert await reg.get("sess-2") is None


@pytest.mark.asyncio
async def test_register_duplicate_raises():
    reg = LoginSessionRegistry(ttl_seconds=60)
    await reg.register(_Stub("sess-dup"), backend_id="bkd-1")
    with pytest.raises(ValueError, match="already registered"):
        await reg.register(_Stub("sess-dup"), backend_id="bkd-1")


@pytest.mark.asyncio
async def test_done_session_removable():
    reg = LoginSessionRegistry(ttl_seconds=60)
    s = _Stub("sess-3")
    await reg.register(s, backend_id="bkd-1")
    await s.cancel()
    await reg.remove("sess-3")
    assert await reg.get("sess-3") is None
