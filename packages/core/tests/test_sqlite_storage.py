from pathlib import Path

import pytest

from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.testing import run_storage_conformance


@pytest.mark.asyncio
async def test_sqlite_storage_conformance(tmp_path: Path) -> None:
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await run_storage_conformance(storage)
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_migrate_is_idempotent(tmp_path: Path) -> None:
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await storage.migrate()  # must not raise
    finally:
        await storage.close()
