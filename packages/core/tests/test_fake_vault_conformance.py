import pytest

from ai_accounts_core.testing import FakeVault, run_vault_conformance


@pytest.mark.asyncio
async def test_fake_vault_passes_conformance():
    await run_vault_conformance(FakeVault())
