import pytest

from ai_accounts_core.backends.opencode import OpenCodeBackend


@pytest.mark.asyncio
async def test_validate_returns_false_when_no_providers(tmp_path):
    backend = OpenCodeBackend()
    ok = await backend.validate(b"", isolation_dir=tmp_path)
    assert ok is False
