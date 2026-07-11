"""Keep-alive pass — pings READY and ERROR accounts, skips the rest."""

from __future__ import annotations

import pytest
from ai_accounts_core.domain.backend import BackendStatus
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.testing import FakeBackend, FakeStorage, FakeVault
from ai_accounts_litestar.app import _keep_alive_pass


@pytest.mark.asyncio
async def test_keep_alive_pass_pings_ready_and_error_only(tmp_path, monkeypatch):
    storage = FakeStorage()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage,
        vault=FakeVault(),
        backends={"fake": fake},
        isolation_base_dir=tmp_path / "iso",
    )
    ready = await accounts.create("fake", display_name="ready")
    await accounts.store_credential(ready.id, b"sk-fake-1")
    await accounts.validate(ready.id)
    errored = await accounts.create("fake", display_name="errored")
    await accounts.store_credential(errored.id, b"sk-fake-2")
    await accounts._update_status(await accounts.get(errored.id), BackendStatus.ERROR)
    fresh = await accounts.create("fake", display_name="fresh")  # UNCONFIGURED

    pinged: list[str] = []
    real = AccountService.keep_alive

    async def spy(self, backend_id):
        pinged.append(backend_id)
        return await real(self, backend_id)

    monkeypatch.setattr(AccountService, "keep_alive", spy)
    await _keep_alive_pass(accounts)

    assert set(pinged) == {ready.id, errored.id}
    assert fresh.id not in pinged
    # keep_alive doubles as recovery: the clean fake ping promotes ERROR → READY.
    assert (await accounts.get(errored.id)).status is BackendStatus.READY
