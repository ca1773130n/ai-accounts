"""SQLite writers must WAIT for the lock, not fail instantly.

WAL lets readers and one writer proceed concurrently; it does NOT serialise two
writers. Python's 5 s default meant a second writer raised
``OperationalError: database is locked`` rather than queueing — which failed
2,295 of 2,701 downstream result-extraction runs (85%) on 2026-07-27, because
each run holds a write transaction across a multi-second LLM round-trip.
"""
import asyncio
import pathlib

import aiosqlite
import pytest

from ai_accounts_core.adapters.storage_sqlite import SqliteStorage


@pytest.mark.asyncio
async def test_connection_sets_a_busy_timeout(tmp_path: pathlib.Path) -> None:
    store = SqliteStorage(str(tmp_path / "s.db"))
    conn = await store._ensure_conn()
    try:
        for pragma, expected in (
            ("journal_mode", "wal"),
            ("busy_timeout", SqliteStorage.BUSY_TIMEOUT_MS),
            ("foreign_keys", 1),
        ):
            cur = await conn.execute(f"PRAGMA {pragma}")
            assert (await cur.fetchone())[0] == expected, pragma
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_writers_queue_behind_a_long_holder(tmp_path: pathlib.Path) -> None:
    """The regression itself: a holder outliving SQLite's 5 s default.

    Without the pragma every concurrent writer fails immediately. With it they
    all commit once the holder releases.
    """
    path = str(tmp_path / "c.db")
    setup = SqliteStorage(path)
    conn = await setup._ensure_conn()
    await conn.execute("CREATE TABLE t (v TEXT)")
    await conn.commit()

    holder = await aiosqlite.connect(path)
    await holder.execute("BEGIN IMMEDIATE")
    await holder.execute("INSERT INTO t VALUES ('holder')")

    errors: list[str] = []

    async def writer(tag: str) -> None:
        store = SqliteStorage(path)
        c = await store._ensure_conn()
        try:
            await c.execute("INSERT INTO t VALUES (?)", (tag,))
            await c.commit()
        except Exception as exc:  # noqa: BLE001 — the assertion is "none of these"
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            await c.close()

    async def release() -> None:
        # 6.5 s > SQLite's 5 s default, so this fails without the pragma.
        await asyncio.sleep(6.5)
        await holder.commit()
        await holder.close()

    await asyncio.gather(release(), *(writer(f"w{i}") for i in range(3)))
    assert errors == [], errors

    cur = await conn.execute("SELECT count(*) FROM t")
    assert (await cur.fetchone())[0] == 4  # holder + 3 writers
    await conn.close()
