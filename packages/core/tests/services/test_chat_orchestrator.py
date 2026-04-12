import pytest

from ai_accounts_core.services.chat_orchestrator import ChatOrchestrator
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.scheduler import AccountScheduler
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.testing.fakes import FakeStorage, FakeVault, FakeBackend


@pytest.fixture
async def orchestrator(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage, vault=vault, backends={"fake": fake}, isolation_base_dir=tmp_path
    )
    backend = await accounts.create(kind="fake", display_name="Test")
    await accounts.store_credential(backend.id, b"sk-fake")
    await accounts.validate(backend.id)
    chat = ChatService(account_service=accounts, storage=storage)
    scheduler = AccountScheduler(account_service=accounts, storage=storage)
    session = await chat.create_session(backend_id=backend.id, model="fake-1")
    return ChatOrchestrator(chat_service=chat, scheduler=scheduler), session.id


@pytest.mark.asyncio
async def test_send_single_streams(orchestrator):
    orch, session_id = orchestrator
    events = []
    async for event in orch.send_single(session_id=session_id, content="Hello"):
        events.append(event)
    kinds = [e.kind for e in events]
    assert "token" in kinds
    assert "done" in kinds
