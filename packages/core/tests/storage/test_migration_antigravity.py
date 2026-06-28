"""Tests for the v3 data migration renaming kind 'gemini' -> 'antigravity'.

Pre-existing databases created before the Antigravity rename hold
``backends`` rows with ``kind='gemini'``. The v3 migration rewrites those
rows in place so the post-rename backend registry (which only knows the
``antigravity`` kind) can load them.
"""

from __future__ import annotations

import aiosqlite
import pytest
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.storage_sqlite.migrations import CURRENT_VERSION


async def _build_v2_db(db_path: str) -> None:
    """Hand-build a v2-shaped DB with a single ``kind='gemini'`` backend."""
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        await conn.execute("INSERT INTO schema_version (version) VALUES (2)")
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
                rate_limit_reason TEXT,
                last_used_at TEXT,
                last_polled_at TEXT
            )
            """
        )
        await conn.execute(
            "INSERT INTO backends "
            "(id, kind, display_name, config, status, created_at) "
            "VALUES ('bkd-gem', 'gemini', 'Gemini', '{}', 'ready', "
            "'2024-01-01T00:00:00Z')"
        )
        # A non-gemini row must be left untouched.
        await conn.execute(
            "INSERT INTO backends "
            "(id, kind, display_name, config, status, created_at) "
            "VALUES ('bkd-cl', 'claude', 'Claude', '{}', 'ready', "
            "'2024-01-01T00:00:00Z')"
        )
        await conn.commit()
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_current_version_is_3():
    assert CURRENT_VERSION == 3


@pytest.mark.asyncio
async def test_v2_db_renames_gemini_to_antigravity(tmp_path):
    db_path = str(tmp_path / "pre_v3.db")
    await _build_v2_db(db_path)

    storage = SqliteStorage(db_path)
    await storage.migrate()
    conn = await storage._ensure_conn()  # type: ignore[attr-defined]

    # The gemini row is rewritten to antigravity.
    async with conn.execute(
        "SELECT kind FROM backends WHERE id = 'bkd-gem'"
    ) as cur:
        (kind,) = await cur.fetchone()
    assert kind == "antigravity"

    # The unrelated row is untouched.
    async with conn.execute(
        "SELECT kind FROM backends WHERE id = 'bkd-cl'"
    ) as cur:
        (other_kind,) = await cur.fetchone()
    assert other_kind == "claude"

    # No gemini rows remain.
    async with conn.execute(
        "SELECT COUNT(*) FROM backends WHERE kind = 'gemini'"
    ) as cur:
        (count,) = await cur.fetchone()
    assert count == 0

    # Version bumped to 3.
    async with conn.execute("SELECT MAX(version) FROM schema_version") as cur:
        (version,) = await cur.fetchone()
    assert version == CURRENT_VERSION == 3

    await storage.close()
