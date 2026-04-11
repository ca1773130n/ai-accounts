from pathlib import Path

import pytest

from ai_accounts_core.login import LoginSession
from ai_accounts_core.login.registry import LoginSessionRegistry
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.testing import FakeBackend, FakeStorage, FakeVault


@pytest.mark.asyncio
async def test_begin_login_registers_session(tmp_path: Path):
    storage = FakeStorage()
    registry = LoginSessionRegistry()
    service = AccountService(
        storage=storage,
        vault=FakeVault(),
        backends={"fake": FakeBackend()},
        isolation_base_dir=tmp_path / "iso",
        login_registry=registry,
    )
    created = await service.create(kind="fake", display_name="X", config={})
    session = await service.begin_login(
        created.id,
        flow_kind="api_key",
        inputs={},
    )
    assert isinstance(session, LoginSession)
    assert await registry.get(session.session_id) is session


@pytest.mark.asyncio
async def test_begin_login_unknown_backend_raises(tmp_path: Path):
    service = AccountService(
        storage=FakeStorage(),
        vault=FakeVault(),
        backends={"fake": FakeBackend()},
        isolation_base_dir=tmp_path / "iso",
    )
    from ai_accounts_core.services.errors import BackendNotFound

    with pytest.raises(BackendNotFound):
        await service.begin_login("bkd-nope", flow_kind="api_key", inputs={})
