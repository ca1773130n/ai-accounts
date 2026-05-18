"""Per-test isolation of the shared model cache (mirror of core tests).

See ``packages/core/tests/conftest.py`` for rationale.
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
