from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.domain.backend import Backend, BackendStatus
from ai_accounts_core.domain.usage import FallbackChainEntry, UsageWindow
from ai_accounts_core.testing import FakeStorage


async def _seed_backend(storage, backend_id: str = "bkd-test1") -> None:
    """Insert a backend so FK constraints are satisfied."""
    repo = await storage.backends()
    await repo.create(
        Backend(
            id=backend_id,
            kind="claude",
            display_name="Test Claude",
            config={},
            status=BackendStatus.READY,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )


# ── put_snapshot + get_latest_snapshots (SQLite) ─────────────


@pytest.mark.asyncio
async def test_put_and_get_snapshots_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await _seed_backend(storage)

        repo = await storage.usage()
        windows = [
            UsageWindow(window_type="daily", usage_percent=50.0, resets_at=datetime(2026, 4, 13, tzinfo=UTC), tokens_used=500, tokens_limit=1000),
            UsageWindow(window_type="monthly", usage_percent=10.0, resets_at=datetime(2026, 5, 1, tzinfo=UTC)),
        ]
        await repo.put_snapshot("bkd-test1", windows)

        result = await repo.get_latest_snapshots("bkd-test1")
        assert len(result) == 2
        types = {w.window_type for w in result}
        assert types == {"daily", "monthly"}

        daily = next(w for w in result if w.window_type == "daily")
        assert daily.usage_percent == 50.0
        assert daily.tokens_used == 500
        assert daily.tokens_limit == 1000
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_put_and_get_snapshots_fake():
    storage = FakeStorage()
    await _seed_backend(storage)

    repo = await storage.usage()
    windows = [
        UsageWindow(window_type="daily", usage_percent=50.0, resets_at=datetime(2026, 4, 13, tzinfo=UTC), tokens_used=500, tokens_limit=1000),
        UsageWindow(window_type="monthly", usage_percent=10.0, resets_at=datetime(2026, 5, 1, tzinfo=UTC)),
    ]
    await repo.put_snapshot("bkd-test1", windows)

    result = await repo.get_latest_snapshots("bkd-test1")
    assert len(result) == 2
    types = {w.window_type for w in result}
    assert types == {"daily", "monthly"}

    daily = next(w for w in result if w.window_type == "daily")
    assert daily.usage_percent == 50.0
    assert daily.tokens_used == 500
    assert daily.tokens_limit == 1000


# ── Deduplication ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_latest_deduplicates_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await _seed_backend(storage)

        repo = await storage.usage()
        await repo.put_snapshot("bkd-test1", [UsageWindow(window_type="daily", usage_percent=20.0, resets_at=None)])
        await repo.put_snapshot("bkd-test1", [UsageWindow(window_type="daily", usage_percent=80.0, resets_at=None)])

        result = await repo.get_latest_snapshots("bkd-test1")
        assert len(result) == 1
        assert result[0].usage_percent == 80.0
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_get_latest_deduplicates_fake():
    storage = FakeStorage()
    await _seed_backend(storage)

    repo = await storage.usage()
    await repo.put_snapshot("bkd-test1", [UsageWindow(window_type="daily", usage_percent=20.0, resets_at=None)])
    await repo.put_snapshot("bkd-test1", [UsageWindow(window_type="daily", usage_percent=80.0, resets_at=None)])

    result = await repo.get_latest_snapshots("bkd-test1")
    assert len(result) == 1
    assert result[0].usage_percent == 80.0


# ── Empty snapshots ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_snapshots_empty_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        repo = await storage.usage()
        result = await repo.get_latest_snapshots("bkd-nonexistent")
        assert result == []
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_get_snapshots_empty_fake():
    storage = FakeStorage()
    repo = await storage.usage()
    result = await repo.get_latest_snapshots("bkd-nonexistent")
    assert result == []


# ── Rate limiting ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_and_get_rate_limit_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await _seed_backend(storage)

        repo = await storage.usage()
        until = datetime(2026, 4, 12, 14, 0, tzinfo=UTC)
        await repo.set_rate_limited("bkd-test1", until, "quota exceeded")

        dt, reason = await repo.get_rate_limit_state("bkd-test1")
        assert dt == until
        assert reason == "quota exceeded"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_set_and_get_rate_limit_fake():
    storage = FakeStorage()
    await _seed_backend(storage)

    repo = await storage.usage()
    until = datetime(2026, 4, 12, 14, 0, tzinfo=UTC)
    await repo.set_rate_limited("bkd-test1", until, "quota exceeded")

    dt, reason = await repo.get_rate_limit_state("bkd-test1")
    assert dt == until
    assert reason == "quota exceeded"


@pytest.mark.asyncio
async def test_clear_rate_limit_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await _seed_backend(storage)

        repo = await storage.usage()
        until = datetime(2026, 4, 12, 14, 0, tzinfo=UTC)
        await repo.set_rate_limited("bkd-test1", until, "quota exceeded")
        await repo.clear_rate_limited("bkd-test1")

        dt, reason = await repo.get_rate_limit_state("bkd-test1")
        assert dt is None
        assert reason is None
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_clear_rate_limit_fake():
    storage = FakeStorage()
    await _seed_backend(storage)

    repo = await storage.usage()
    until = datetime(2026, 4, 12, 14, 0, tzinfo=UTC)
    await repo.set_rate_limited("bkd-test1", until, "quota exceeded")
    await repo.clear_rate_limited("bkd-test1")

    dt, reason = await repo.get_rate_limit_state("bkd-test1")
    assert dt is None
    assert reason is None


@pytest.mark.asyncio
async def test_get_rate_limit_state_default_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await _seed_backend(storage)

        repo = await storage.usage()
        dt, reason = await repo.get_rate_limit_state("bkd-test1")
        assert dt is None
        assert reason is None
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_get_rate_limit_state_default_fake():
    storage = FakeStorage()
    await _seed_backend(storage)

    repo = await storage.usage()
    dt, reason = await repo.get_rate_limit_state("bkd-test1")
    assert dt is None
    assert reason is None


# ── Fallback chain ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_and_get_chain_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await _seed_backend(storage, "bkd-test1")
        await _seed_backend(storage, "bkd-test2")

        repo = await storage.usage()
        entries = [
            FallbackChainEntry(backend_id="bkd-test2", priority=2),
            FallbackChainEntry(backend_id="bkd-test1", priority=1),
        ]
        await repo.set_chain(entries)

        chain = await repo.get_chain()
        assert len(chain) == 2
        assert chain[0].backend_id == "bkd-test1"
        assert chain[0].priority == 1
        assert chain[1].backend_id == "bkd-test2"
        assert chain[1].priority == 2
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_set_and_get_chain_fake():
    storage = FakeStorage()
    await _seed_backend(storage, "bkd-test1")
    await _seed_backend(storage, "bkd-test2")

    repo = await storage.usage()
    entries = [
        FallbackChainEntry(backend_id="bkd-test2", priority=2),
        FallbackChainEntry(backend_id="bkd-test1", priority=1),
    ]
    await repo.set_chain(entries)

    chain = await repo.get_chain()
    assert len(chain) == 2
    assert chain[0].backend_id == "bkd-test1"
    assert chain[0].priority == 1
    assert chain[1].backend_id == "bkd-test2"
    assert chain[1].priority == 2


@pytest.mark.asyncio
async def test_set_chain_replaces_previous_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await _seed_backend(storage, "bkd-test1")
        await _seed_backend(storage, "bkd-test2")

        repo = await storage.usage()
        await repo.set_chain([
            FallbackChainEntry(backend_id="bkd-test1", priority=1),
            FallbackChainEntry(backend_id="bkd-test2", priority=2),
        ])
        await repo.set_chain([
            FallbackChainEntry(backend_id="bkd-test2", priority=1),
        ])

        chain = await repo.get_chain()
        assert len(chain) == 1
        assert chain[0].backend_id == "bkd-test2"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_set_chain_replaces_previous_fake():
    storage = FakeStorage()
    await _seed_backend(storage, "bkd-test1")
    await _seed_backend(storage, "bkd-test2")

    repo = await storage.usage()
    await repo.set_chain([
        FallbackChainEntry(backend_id="bkd-test1", priority=1),
        FallbackChainEntry(backend_id="bkd-test2", priority=2),
    ])
    await repo.set_chain([
        FallbackChainEntry(backend_id="bkd-test2", priority=1),
    ])

    chain = await repo.get_chain()
    assert len(chain) == 1
    assert chain[0].backend_id == "bkd-test2"


@pytest.mark.asyncio
async def test_get_chain_empty_sqlite(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        repo = await storage.usage()
        chain = await repo.get_chain()
        assert chain == []
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_get_chain_empty_fake():
    storage = FakeStorage()
    repo = await storage.usage()
    chain = await repo.get_chain()
    assert chain == []
