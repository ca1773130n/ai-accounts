"""Tests for the versioned migration system in the SQLite storage adapter.

The key scenario we protect against is a pre-0.3.0 database that was
created before the rate-limit columns existed on ``backends``. Under the
old ``CREATE TABLE IF NOT EXISTS``-only ``migrate()``, such a database
would keep loading successfully but every query touching a rate-limit
column would fail with ``no such column``. Downstream consumers (notably
HypePaper) had to hand-roll backfill logic for this. Now the migration
system handles it automatically.
"""

from __future__ import annotations

import aiosqlite
import pytest

from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.storage_sqlite.migrations import (
    CURRENT_VERSION,
    apply_migrations,
)


async def _columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    return {row[1] for row in rows}


@pytest.mark.asyncio
async def test_fresh_db_ends_at_current_version(tmp_path):
    storage = SqliteStorage(str(tmp_path / "fresh.db"))
    await storage.migrate()
    conn = await storage._ensure_conn()  # type: ignore[attr-defined]
    async with conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ) as cur:
        (version,) = await cur.fetchone()
    assert version == CURRENT_VERSION
    await storage.close()


@pytest.mark.asyncio
async def test_fresh_db_has_all_current_columns(tmp_path):
    storage = SqliteStorage(str(tmp_path / "fresh.db"))
    await storage.migrate()
    conn = await storage._ensure_conn()  # type: ignore[attr-defined]
    cols = await _columns(conn, "backends")
    # The four columns added in v2 must be present on fresh installs too.
    assert {
        "rate_limited_until",
        "rate_limit_reason",
        "last_used_at",
        "last_polled_at",
    } <= cols
    await storage.close()


@pytest.mark.asyncio
async def test_pre_v2_db_is_upgraded_to_current(tmp_path):
    """Simulate a pre-0.3.0 database (v1 schema, no rate-limit columns) and
    verify migrate() adds the missing columns and bumps the version."""
    db_path = tmp_path / "pre_v2.db"

    # Hand-build a v1-shaped DB: backends table without the 4 late columns.
    conn = await aiosqlite.connect(str(db_path))
    try:
        await conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY)"
        )
        await conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        await conn.execute(
            """
            CREATE TABLE backends (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                display_name TEXT NOT NULL,
                config TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                last_error TEXT
            )
            """
        )
        # Insert a row so we can verify it survives the ALTER TABLE.
        await conn.execute(
            "INSERT INTO backends "
            "(id, kind, display_name, config, status, created_at) "
            "VALUES ('bkd-1', 'claude', 'claude-1', '{}', 'ready', '2024-01-01T00:00:00Z')"
        )
        await conn.commit()
    finally:
        await conn.close()

    # Now migrate as if upgrading to the current version.
    storage = SqliteStorage(str(db_path))
    await storage.migrate()
    conn = await storage._ensure_conn()  # type: ignore[attr-defined]
    cols = await _columns(conn, "backends")
    assert "rate_limited_until" in cols
    assert "rate_limit_reason" in cols
    assert "last_used_at" in cols
    assert "last_polled_at" in cols

    # Pre-existing row survives.
    async with conn.execute(
        "SELECT id, kind, rate_limited_until FROM backends WHERE id = 'bkd-1'"
    ) as cur:
        row = await cur.fetchone()
    assert row == ("bkd-1", "claude", None)

    # Version bumped.
    async with conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ) as cur:
        (version,) = await cur.fetchone()
    assert version == CURRENT_VERSION
    await storage.close()


@pytest.mark.asyncio
async def test_migrate_is_idempotent(tmp_path):
    """Running migrate twice must not raise and must not duplicate work."""
    storage = SqliteStorage(str(tmp_path / "idem.db"))
    await storage.migrate()
    await storage.migrate()  # no-op second run
    conn = await storage._ensure_conn()  # type: ignore[attr-defined]
    cols = await _columns(conn, "backends")
    assert "rate_limited_until" in cols
    await storage.close()


@pytest.mark.asyncio
async def test_partial_backfill_tolerated(tmp_path):
    """If an out-of-band backfill (e.g. HypePaper's old workaround) already
    added some of the v2 columns, the migration must skip them cleanly."""
    db_path = tmp_path / "partial.db"

    conn = await aiosqlite.connect(str(db_path))
    try:
        await conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY)"
        )
        await conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        await conn.execute(
            """
            CREATE TABLE backends (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                display_name TEXT NOT NULL,
                config TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                last_error TEXT,
                rate_limited_until TEXT,
                rate_limit_reason TEXT
            )
            """
        )
        await conn.commit()
    finally:
        await conn.close()

    # Migration should add the two *missing* columns and leave the two
    # existing ones alone.
    conn = await aiosqlite.connect(str(db_path))
    try:
        # Read schema.sql the same way storage.py does.
        from pathlib import Path
        schema_path = (
            Path(__file__).resolve().parent.parent.parent
            / "src" / "ai_accounts_core" / "adapters" / "storage_sqlite" / "schema.sql"
        )
        baseline = schema_path.read_text()
        await apply_migrations(conn, baseline_schema=baseline)
        cols = await _columns(conn, "backends")
        assert {
            "rate_limited_until",
            "rate_limit_reason",
            "last_used_at",
            "last_polled_at",
        } <= cols
    finally:
        await conn.close()
