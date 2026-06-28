from __future__ import annotations

import pytest
from ai_accounts_core.backends.antigravity import AntigravityBackend


@pytest.mark.asyncio
async def test_antigravity_usage_returns_empty(tmp_path):
    # Safe-paths-only: no sanctioned quota API for the AI Studio key or the
    # CLIProxyAPI OAuth flow, so get_usage is intentionally a no-op. (The old
    # cloudcode-pa /v1internal call was removed — account-ban risk.)
    backend = AntigravityBackend()
    assert await backend.get_usage(b"ya29.token", isolation_dir=tmp_path) == []
    assert await backend.get_usage(b"", isolation_dir=tmp_path) == []
