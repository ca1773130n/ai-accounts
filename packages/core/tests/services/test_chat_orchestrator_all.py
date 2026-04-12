import pytest

from ai_accounts_core.services.chat_orchestrator import ChatOrchestrator
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.scheduler import AccountScheduler
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.testing.fakes import FakeStorage, FakeVault, FakeBackend


@pytest.fixture
async def multi_orchestrator(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage, vault=vault, backends={"fake": fake}, isolation_base_dir=tmp_path,
    )
    b1 = await accounts.create(kind="fake", display_name="A1")
    await accounts.store_credential(b1.id, b"sk-fake-1")
    await accounts.validate(b1.id)
    b2 = await accounts.create(kind="fake", display_name="A2")
    await accounts.store_credential(b2.id, b"sk-fake-2")
    await accounts.validate(b2.id)
    chat = ChatService(account_service=accounts, storage=storage)
    scheduler = AccountScheduler(account_service=accounts, storage=storage)
    session = await chat.create_session(backend_id=b1.id, model="fake-1")
    return ChatOrchestrator(chat_service=chat, scheduler=scheduler), session.id


@pytest.mark.asyncio
async def test_send_all_fans_out(multi_orchestrator):
    orch, sid = multi_orchestrator
    events = []
    async for event in orch.send_all(session_id=sid, content="Hello"):
        events.append(event)
    # Should have backend_delta and backend_complete events
    deltas = [e for e in events if e.kind == "backend_delta"]
    completes = [e for e in events if e.kind == "backend_complete"]
    assert len(deltas) >= 1
    assert len(completes) >= 1


@pytest.mark.asyncio
async def test_send_all_no_backends(tmp_path):
    """When no backends are READY, send_all yields a backend_error."""
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage, vault=vault, backends={"fake": fake}, isolation_base_dir=tmp_path,
    )
    chat = ChatService(account_service=accounts, storage=storage)
    scheduler = AccountScheduler(account_service=accounts, storage=storage)
    # Create a session by first making a backend (needed for create_session), then
    # we won't validate it so it stays non-READY — but we need a valid session_id.
    b = await accounts.create(kind="fake", display_name="unused")
    await accounts.store_credential(b.id, b"sk-fake")
    await accounts.validate(b.id)
    session = await chat.create_session(backend_id=b.id, model="fake-1")
    # Delete the backend so the scheduler sees nothing READY
    await accounts.delete(b.id)

    orch = ChatOrchestrator(chat_service=chat, scheduler=scheduler)
    events = []
    async for event in orch.send_all(session_id=session.id, content="Hello"):
        events.append(event)
    assert len(events) == 1
    assert events[0].kind == "backend_error"
    assert events[0].backend == "none"


@pytest.mark.asyncio
async def test_send_all_delta_text_matches(multi_orchestrator):
    """All deltas combined should contain the FakeBackend output at least once."""
    orch, sid = multi_orchestrator
    texts: dict[str, str] = {}
    async for event in orch.send_all(session_id=sid, content="Test"):
        if event.kind == "backend_delta" and event.text:
            texts.setdefault(event.backend, "")
            texts[event.backend] += event.text
    # Both backends are kind="fake" so deltas accumulate under one key.
    # Each backend run produces "Hello world!" — with two READY backends
    # of the same kind we get two runs under the same key.
    assert "fake" in texts
    assert "Hello world!" in texts["fake"]
