"""Shared conformance suite for StorageProtocol implementations.

Usage in an adapter's test module:

    import pytest
    from ai_accounts_core.testing import run_storage_conformance

    @pytest.mark.asyncio
    async def test_my_storage(tmp_path):
        storage = MyStorage(path=tmp_path / "x.db")
        await run_storage_conformance(storage)
"""

from datetime import UTC, datetime

from ai_accounts_core.domain.backend import (
    Backend,
    BackendCredential,
    BackendKind,
    BackendStatus,
)
from ai_accounts_core.domain.chat import ChatMessage, ChatRole, ChatSession
from ai_accounts_core.domain.onboarding import OnboardingState, OnboardingStep
from ai_accounts_core.domain.session import LiveSession, SessionKind, SessionState
from ai_accounts_core.protocols.storage import StorageProtocol


async def run_storage_conformance(storage: StorageProtocol) -> None:
    await storage.migrate()
    await _test_backend_crud(storage)
    await _test_credential_crud(storage)
    await _test_history(storage)
    await _test_sessions(storage)
    await _test_onboarding(storage)


async def _test_backend_crud(storage: StorageProtocol) -> None:
    repo = await storage.backends()
    now = datetime.now(UTC)
    backend = Backend(
        id="bkd-1",
        kind=BackendKind.CLAUDE,
        display_name="Test Claude",
        config={},
        status=BackendStatus.UNCONFIGURED,
        created_at=now,
    )
    await repo.create(backend)
    fetched = await repo.get("bkd-1")
    assert fetched == backend
    assert await repo.list() == [backend]

    updated = Backend(
        id="bkd-1",
        kind=BackendKind.CLAUDE,
        display_name="Renamed",
        config={"foo": "bar"},
        status=BackendStatus.READY,
        created_at=now,
        updated_at=datetime.now(UTC),
    )
    await repo.update(updated)
    refetched = await repo.get("bkd-1")
    assert refetched is not None
    assert refetched.display_name == "Renamed"

    await repo.delete("bkd-1")
    assert await repo.get("bkd-1") is None
    assert await repo.list() == []


async def _test_credential_crud(storage: StorageProtocol) -> None:
    repo = await storage.backends()
    await repo.create(
        Backend(
            id="bkd-2",
            kind=BackendKind.OPENCODE,
            display_name="x",
            config={},
            status=BackendStatus.READY,
            created_at=datetime.now(UTC),
        )
    )
    cred = BackendCredential(
        id="crd-1",
        backend_id="bkd-2",
        ciphertext=b"\xde\xad\xbe\xef",
        key_id="local/v1",
        created_at=datetime.now(UTC),
    )
    await repo.put_credential(cred)
    assert await repo.get_credential("bkd-2") == cred
    await repo.delete_credential("bkd-2")
    assert await repo.get_credential("bkd-2") is None
    await repo.delete("bkd-2")


async def _test_history(storage: StorageProtocol) -> None:
    backends_repo = await storage.backends()
    await backends_repo.create(
        Backend(
            id="bkd-3",
            kind=BackendKind.CLAUDE,
            display_name="x",
            config={},
            status=BackendStatus.READY,
            created_at=datetime.now(UTC),
        )
    )
    history = await storage.history()
    session = ChatSession(
        id="sess-1",
        backend_id="bkd-3",
        title="First chat",
        created_at=datetime.now(UTC),
    )
    await history.create_session(session)
    msg = ChatMessage(
        id="msg-1",
        session_id="sess-1",
        role=ChatRole.USER,
        content="hello",
        created_at=datetime.now(UTC),
    )
    await history.append_message(msg)
    assert await history.list_messages("sess-1") == [msg]
    assert await history.list_sessions("bkd-3") == [session]

    # delete_session, and specifically that the MESSAGES go with it.
    #
    # In the SQLite adapter that comes from ON DELETE CASCADE plus
    # foreign_keys=ON, not from a second DELETE. Asserting it here rather than
    # in the adapter's own test is deliberate: an in-memory fake that forgot to
    # drop the messages would otherwise let a caller's test pass against
    # behaviour the real store does not have, and the leak this method exists
    # to fix is precisely orphaned message rows.
    second = ChatSession(
        id="sess-2",
        backend_id="bkd-3",
        title="Second chat",
        created_at=datetime.now(UTC),
    )
    await history.create_session(second)
    await history.append_message(
        ChatMessage(
            id="msg-2",
            session_id="sess-2",
            role=ChatRole.USER,
            content="ephemeral",
            created_at=datetime.now(UTC),
        )
    )

    assert await history.delete_session("sess-2") is True
    assert await history.list_messages("sess-2") == []
    assert await history.list_sessions("bkd-3") == [session]

    # Idempotent, and safe on an id that never existed — callers delete from a
    # `finally`, where raising would mask the original exception.
    assert await history.delete_session("sess-2") is False
    assert await history.delete_session("never-existed") is False

    # The unrelated session and its messages are untouched.
    assert await history.list_messages("sess-1") == [msg]


async def _test_sessions(storage: StorageProtocol) -> None:
    repo = await storage.sessions()
    now = datetime.now(UTC)
    session = LiveSession(
        id="live-1",
        kind=SessionKind.CHAT,
        backend_id="bkd-3",
        state=SessionState.ACTIVE,
        started_at=now,
        last_seen_at=now,
    )
    await repo.upsert(session)
    assert await repo.get("live-1") == session
    assert len(await repo.list_active()) == 1
    await repo.end("live-1")
    assert await repo.get("live-1") is None


async def _test_onboarding(storage: StorageProtocol) -> None:
    repo = await storage.onboarding()
    state = OnboardingState(id="onb-1", current_step=OnboardingStep.WELCOME)
    await repo.put(state)
    assert await repo.get("onb-1") == state
