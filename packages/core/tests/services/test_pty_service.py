import pytest
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.pty import PtyService
from ai_accounts_core.testing.fakes import FakeBackend, FakeStorage, FakeVault


@pytest.fixture
async def pty_service(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage,
        vault=vault,
        backends={"fake": fake},
        isolation_base_dir=tmp_path,
    )
    backend = await accounts.create(kind="fake", display_name="Test")
    await accounts.store_credential(backend.id, b"sk-fake-test")
    await accounts.validate(backend.id)
    return PtyService(account_service=accounts, storage=storage), backend.id


@pytest.mark.asyncio
async def test_spawn_session(pty_service):
    svc, backend_id = pty_service
    session_id, handle = await svc.spawn(
        backend_id=backend_id,
        command=("/bin/echo", "hi"),
        cols=80,
        rows=24,
    )
    assert session_id.startswith("pty-")
    assert handle is not None
    await handle.close()


@pytest.mark.asyncio
async def test_attach_and_kill(pty_service):
    svc, backend_id = pty_service
    session_id, handle = await svc.spawn(
        backend_id=backend_id,
        command=("/bin/sh",),
        cols=80,
        rows=24,
    )
    assert svc.attach(session_id) is handle
    await svc.kill(session_id)
    assert svc.attach(session_id) is None
