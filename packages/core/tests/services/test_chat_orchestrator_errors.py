"""Tests for the new no-models error paths added in chat_orchestrator.

The orchestrator used to fall back to model="auto" when list_models()
returned [] or threw — and CLIProxyAPI then 502'd with "unknown provider for
model auto". Now it emits an explicit backend_error / synthesis_error and
skips the backend.
"""

from __future__ import annotations

import pytest
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.chat_orchestrator import ChatOrchestrator
from ai_accounts_core.services.scheduler import AccountScheduler
from ai_accounts_core.testing.fakes import FakeBackend, FakeStorage, FakeVault


@pytest.fixture
async def orchestrator_with_one_backend(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage,
        vault=vault,
        backends={"fake": fake},
        isolation_base_dir=tmp_path,
    )
    b = await accounts.create(kind="fake", display_name="A1")
    await accounts.store_credential(b.id, b"sk-fake-1")
    await accounts.validate(b.id)
    chat = ChatService(account_service=accounts, storage=storage)
    scheduler = AccountScheduler(account_service=accounts, storage=storage)
    session = await chat.create_session(backend_id=b.id, model="fake-1")
    return (
        ChatOrchestrator(chat_service=chat, scheduler=scheduler),
        session.id,
        b.id,
        fake,
    )


@pytest.mark.asyncio
async def test_send_all_emits_backend_error_when_list_models_throws(
    orchestrator_with_one_backend,
):
    orch, sid, bid, fake = orchestrator_with_one_backend

    async def boom(*a, **kw):
        raise RuntimeError("fake list_models exploded")

    fake.list_models = boom  # type: ignore[method-assign]

    events = [e async for e in orch.send_all(session_id=sid, content="Hi")]
    errs = [e for e in events if e.kind == "backend_error"]
    assert len(errs) == 1
    err = errs[0]
    assert err.backend == bid
    assert err.backend_kind == "fake"
    assert err.error is not None and "could not enumerate models" in err.error
    assert "fake list_models exploded" in err.error
    # No backend_delta / backend_complete should fire when we skip the backend.
    assert not any(e.kind in ("backend_delta", "backend_complete") for e in events)


@pytest.mark.asyncio
async def test_send_all_emits_backend_error_when_list_models_empty(
    orchestrator_with_one_backend,
):
    orch, sid, bid, fake = orchestrator_with_one_backend

    async def empty(*a, **kw):
        return []

    fake.list_models = empty  # type: ignore[method-assign]

    events = [e async for e in orch.send_all(session_id=sid, content="Hi")]
    errs = [e for e in events if e.kind == "backend_error"]
    assert len(errs) == 1
    assert errs[0].backend == bid
    assert errs[0].error == "no models available for fake"
    assert not any(e.kind == "backend_delta" for e in events)


@pytest.mark.asyncio
async def test_send_compound_emits_synthesis_error_when_synth_models_throw(
    orchestrator_with_one_backend,
):
    orch, sid, bid, fake = orchestrator_with_one_backend

    # First call (in send_all) returns models so the fan-out succeeds and
    # produces a response. Second call (in send_compound's synth phase)
    # throws so we exercise the synthesis error path specifically.

    real_list = fake.list_models
    call_count = {"n": 0}

    async def conditional(credential, *, isolation_dir):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return await real_list(credential, isolation_dir=isolation_dir)
        raise RuntimeError("synth list_models failed")

    fake.list_models = conditional  # type: ignore[method-assign]

    events = [e async for e in orch.send_compound(session_id=sid, content="Hi")]
    synth_errors = [e for e in events if e.kind == "synthesis_error"]
    assert len(synth_errors) == 1
    err = synth_errors[0].error or ""
    assert "could not enumerate" in err and "synth list_models failed" in err
    # No synthesis_delta / synthesis_complete should fire.
    assert not any(e.kind in ("synthesis_delta", "synthesis_complete") for e in events)
    # But the fan-out backend_delta should still have happened.
    assert any(e.kind == "backend_delta" for e in events)


@pytest.mark.asyncio
async def test_send_compound_emits_synthesis_error_when_synth_models_empty(
    orchestrator_with_one_backend,
):
    orch, sid, bid, fake = orchestrator_with_one_backend

    real_list = fake.list_models
    call_count = {"n": 0}

    async def conditional(credential, *, isolation_dir):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return await real_list(credential, isolation_dir=isolation_dir)
        return []

    fake.list_models = conditional  # type: ignore[method-assign]

    events = [e async for e in orch.send_compound(session_id=sid, content="Hi")]
    synth_errors = [e for e in events if e.kind == "synthesis_error"]
    assert len(synth_errors) == 1
    assert "no models available for synthesis backend fake" in (synth_errors[0].error or "")
