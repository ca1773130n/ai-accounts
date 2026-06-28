"""Versioned schema migrations for the SQLite storage adapter.

Design:

* ``schema.sql`` is the current full baseline — fresh databases run it once
  and jump straight to ``CURRENT_VERSION``.
* Databases created by older versions of this package have a
  ``schema_version`` row below ``CURRENT_VERSION``. For those,
  ``apply_migrations`` walks the ``MIGRATIONS`` list and applies each
  pending step in order.
* Each migration statement is written defensively (``ADD COLUMN`` tolerated
  via the ``duplicate column`` exception path) so partially-applied
  schemas self-heal instead of crashing on the next boot.

Adding a migration:

1. Bump ``CURRENT_VERSION``.
2. Append a ``Migration`` entry to ``MIGRATIONS`` with the statements that
   take the schema from the previous version to the new one.
3. Also update ``schema.sql`` to reflect the new baseline so fresh
   installs get the final schema without replaying migrations.
4. Add a test under ``packages/core/tests/`` that asserts a pre-migration
   database reaches the new state after ``migrate()``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    statements: tuple[str, ...]


CURRENT_VERSION = 3


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=2,
        description="add rate-limit and usage tracking columns to backends",
        statements=(
            "ALTER TABLE backends ADD COLUMN rate_limited_until TEXT",
            "ALTER TABLE backends ADD COLUMN rate_limit_reason TEXT",
            "ALTER TABLE backends ADD COLUMN last_used_at TEXT",
            "ALTER TABLE backends ADD COLUMN last_polled_at TEXT",
        ),
    ),
    Migration(
        version=3,
        description="rename backend kind 'gemini' to 'antigravity'",
        statements=("UPDATE backends SET kind='antigravity' WHERE kind='gemini'",),
    ),
)


async def _safe_execute(conn: aiosqlite.Connection, stmt: str) -> None:
    """Execute a migration statement, tolerating duplicate-column errors.

    SQLite's ``ALTER TABLE ADD COLUMN`` is not idempotent. If a migration is
    partially re-applied (e.g. an older out-of-band fix already added a
    column), we want to continue rather than abort the whole migration —
    every statement in ``MIGRATIONS`` is written to make this safe.
    """
    try:
        await conn.execute(stmt)
    except Exception as exc:
        msg = str(exc).lower()
        if "duplicate column name" in msg:
            logger.info("migration statement skipped (column already exists): %s", stmt)
            return
        raise


async def apply_migrations(conn: aiosqlite.Connection, *, baseline_schema: str) -> None:
    """Bring the connected database up to ``CURRENT_VERSION``.

    * If no ``schema_version`` row exists, treat the DB as fresh, run the
      baseline ``schema.sql``, and record ``CURRENT_VERSION``.
    * Otherwise apply each pending ``Migration`` in order, recording each
      step in ``schema_version`` as it completes so a crash mid-run resumes
      correctly on the next boot.
    """
    # Ensure the version table itself exists before we read from it — older
    # installs that never called migrate() will not have it.
    await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")

    async with conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version") as cur:
        row = await cur.fetchone()
    current = int(row[0]) if row else 0

    if current == 0:
        # Fresh install — run baseline and record current version.
        logger.info("initializing database schema at version %d", CURRENT_VERSION)
        await conn.executescript(baseline_schema)
        await conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (CURRENT_VERSION,),
        )
        await conn.commit()
        return

    if current >= CURRENT_VERSION:
        return

    logger.info("database schema at version %d, upgrading to %d", current, CURRENT_VERSION)
    # Walk every pending migration. The list is ordered by version so we can
    # just skip ones we've already applied.
    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        logger.info(
            "applying migration v%d: %s",
            migration.version,
            migration.description,
        )
        for stmt in migration.statements:
            await _safe_execute(conn, stmt)
        await conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (migration.version,),
        )
        await conn.commit()


async def current_version(conn: aiosqlite.Connection) -> int:
    """Return the current schema version (0 if not yet migrated)."""
    await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    async with conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version") as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0
