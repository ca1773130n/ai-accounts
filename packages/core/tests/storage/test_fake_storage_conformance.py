import pytest
from ai_accounts_core.testing import FakeStorage, run_storage_conformance


@pytest.mark.asyncio
async def test_fake_storage_passes_conformance():
    await run_storage_conformance(FakeStorage())
