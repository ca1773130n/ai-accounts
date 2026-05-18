import pytest
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.chat_orchestrator import ChatOrchestrator
from ai_accounts_core.services.scheduler import AccountScheduler
from ai_accounts_core.testing.fakes import FakeBackend, FakeStorage, FakeVault


@pytest.fixture
async def multi_orchestrator(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage,
        vault=vault,
        backends={"fake": fake},
        isolation_base_dir=tmp_path,
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
async def test_send_compound_synthesizes(multi_orchestrator):
    orch, sid = multi_orchestrator
    events = []
    async for event in orch.send_compound(session_id=sid, content="Hello"):
        events.append(event)
    kinds = [e.kind for e in events]
    assert "backend_delta" in kinds
    assert "synthesis_start" in kinds
    assert "synthesis_delta" in kinds
    assert "synthesis_complete" in kinds


@pytest.mark.asyncio
async def test_send_compound_synthesis_start_has_metadata(multi_orchestrator):
    orch, sid = multi_orchestrator
    events = []
    async for event in orch.send_compound(session_id=sid, content="Hello"):
        events.append(event)
    starts = [e for e in events if e.kind == "synthesis_start"]
    assert len(starts) == 1
    assert starts[0].primary_backend is not None
    assert starts[0].backends_collected is not None
    assert len(starts[0].backends_collected) >= 1


@pytest.mark.asyncio
async def test_send_compound_synthesis_text(multi_orchestrator):
    """Synthesis deltas should reproduce FakeBackend output."""
    orch, sid = multi_orchestrator
    synth_text = ""
    async for event in orch.send_compound(session_id=sid, content="Hello"):
        if event.kind == "synthesis_delta" and event.text:
            synth_text += event.text
    # FakeBackend always returns "Hello world!" for synthesis too
    assert synth_text == "Hello world!"
