"""Per-test isolation of the shared model cache.

``ai_accounts_core.backends._models_fallback`` writes successful cliproxy
``/v1/models`` snapshots to ``~/.ai-accounts/models_cache.json`` (override
via ``AI_ACCOUNTS_CACHE_DIR``). Without isolation, a real cliproxyapi
running on the dev machine — or an earlier test that exercises the live
path — pollutes the cache and shadows static-fallback assertions in later
tests.

The autouse fixture below pins the cache dir to a unique tmp path per
test, guaranteeing each test starts with an empty snapshot.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_models_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir: Path = tmp_path_factory.mktemp("aia_models_cache")
    monkeypatch.setenv("AI_ACCOUNTS_CACHE_DIR", str(cache_dir))
