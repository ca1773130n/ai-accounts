from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from ai_accounts_core.domain.backend import (
    Backend,
    BackendCredential,
    BackendStatus,
)
from ai_accounts_core.domain.chat import ChatMessage, ChatRole, ChatSession
from ai_accounts_core.domain.onboarding import OnboardingState, OnboardingStep
from ai_accounts_core.domain.session import LiveSession, SessionKind, SessionState
from ai_accounts_core.domain.usage import FallbackChainEntry, UsageWindow
from ai_accounts_core.protocols.storage import (
    BackendRepository,
    HistoryRepository,
    OnboardingRepository,
    SessionRepository,
    UsageRepository,
)

from .migrations import CURRENT_VERSION, apply_migrations

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()
_CURRENT_VERSION = CURRENT_VERSION


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class _SqliteBackendRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(self, backend: Backend) -> None:
        await self._conn.execute(
            "INSERT INTO backends "
            "(id, kind, display_name, config, status, created_at, updated_at, last_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                backend.id,
                backend.kind,
                backend.display_name,
                json.dumps(backend.config),
                backend.status.value,
                _iso(backend.created_at),
                _iso(backend.updated_at) if backend.updated_at else None,
                backend.last_error,
            ),
        )
        await self._conn.commit()

    async def get(self, backend_id: str) -> Backend | None:
        async with self._conn.execute(
            "SELECT id, kind, display_name, config, status, created_at, updated_at, last_error "
            "FROM backends WHERE id = ?",
            (backend_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_backend(row) if row else None

    async def list(self) -> list[Backend]:
        async with self._conn.execute(
            "SELECT id, kind, display_name, config, status, created_at, updated_at, last_error "
            "FROM backends ORDER BY created_at"
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_backend(row) for row in rows]

    async def update(self, backend: Backend) -> None:
        cursor = await self._conn.execute(
            "UPDATE backends SET kind = ?, display_name = ?, config = ?, status = ?, "
            "updated_at = ?, last_error = ? WHERE id = ?",
            (
                backend.kind,
                backend.display_name,
                json.dumps(backend.config),
                backend.status.value,
                _iso(backend.updated_at) if backend.updated_at else None,
                backend.last_error,
                backend.id,
            ),
        )
        if cursor.rowcount == 0:
            raise KeyError(backend.id)
        await self._conn.commit()

    async def delete(self, backend_id: str) -> None:
        await self._conn.execute("DELETE FROM backends WHERE id = ?", (backend_id,))
        await self._conn.commit()

    async def put_credential(self, credential: BackendCredential) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO backend_credentials "
            "(id, backend_id, ciphertext, key_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                credential.id,
                credential.backend_id,
                credential.ciphertext,
                credential.key_id,
                _iso(credential.created_at),
                _iso(credential.expires_at) if credential.expires_at else None,
            ),
        )
        await self._conn.commit()

    async def get_credential(self, backend_id: str) -> BackendCredential | None:
        async with self._conn.execute(
            "SELECT id, backend_id, ciphertext, key_id, created_at, expires_at "
            "FROM backend_credentials WHERE backend_id = ?",
            (backend_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        created_at = _parse_dt(row[4])
        assert created_at is not None
        return BackendCredential(
            id=row[0],
            backend_id=row[1],
            ciphertext=row[2],
            key_id=row[3],
            created_at=created_at,
            expires_at=_parse_dt(row[5]),
        )

    async def delete_credential(self, backend_id: str) -> None:
        await self._conn.execute(
            "DELETE FROM backend_credentials WHERE backend_id = ?", (backend_id,)
        )
        await self._conn.commit()

    def _row_to_backend(self, row: aiosqlite.Row | tuple) -> Backend:  # type: ignore[type-arg]
        created_at = _parse_dt(row[5])
        assert created_at is not None
        return Backend(
            id=row[0],
            kind=row[1],
            display_name=row[2],
            config=json.loads(row[3]),
            status=BackendStatus(row[4]),
            created_at=created_at,
            updated_at=_parse_dt(row[6]),
            last_error=row[7],
        )


class _SqliteSessionRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def upsert(self, session: LiveSession) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO live_sessions "
            "(id, kind, backend_id, state, started_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.kind.value,
                session.backend_id,
                session.state.value,
                _iso(session.started_at),
                _iso(session.last_seen_at),
            ),
        )
        await self._conn.commit()

    async def get(self, session_id: str) -> LiveSession | None:
        async with self._conn.execute(
            "SELECT id, kind, backend_id, state, started_at, last_seen_at "
            "FROM live_sessions WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row(row) if row else None

    async def list_active(self) -> list[LiveSession]:
        async with self._conn.execute(
            "SELECT id, kind, backend_id, state, started_at, last_seen_at "
            "FROM live_sessions WHERE state != 'ended'"
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row(row) for row in rows]

    async def end(self, session_id: str) -> None:
        await self._conn.execute("DELETE FROM live_sessions WHERE id = ?", (session_id,))
        await self._conn.commit()

    def _row(self, row: aiosqlite.Row | tuple) -> LiveSession:  # type: ignore[type-arg]
        started_at = _parse_dt(row[4])
        last_seen_at = _parse_dt(row[5])
        assert started_at is not None
        assert last_seen_at is not None
        return LiveSession(
            id=row[0],
            kind=SessionKind(row[1]),
            backend_id=row[2],
            state=SessionState(row[3]),
            started_at=started_at,
            last_seen_at=last_seen_at,
        )


class _SqliteHistoryRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create_session(self, session: ChatSession) -> None:
        await self._conn.execute(
            "INSERT INTO chat_sessions "
            "(id, backend_id, title, created_at, updated_at, model) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.backend_id,
                session.title,
                _iso(session.created_at),
                _iso(session.updated_at) if session.updated_at else None,
                session.model,
            ),
        )
        await self._conn.commit()

    async def delete_session(self, session_id: str) -> bool:
        """Remove a session and, by cascade, its messages. True if one existed.

        Until this existed the chat tables were append-only by omission — the
        repo could create sessions and append messages and had no way to remove
        either, while backends, credentials and live_sessions all had a delete.
        Every caller that used the chat api for a ONE-SHOT completion therefore
        leaked a session plus its messages permanently. One deployment measured
        3.9 GB, 99,813 sessions and 199,327 messages in nine days, none of it
        ever read back.

        One statement, no explicit transaction: `chat_messages.session_id` is
        declared `ON DELETE CASCADE` (schema.sql:40) and `PRAGMA foreign_keys`
        is ON for every connection (see `_connect`), so the messages go with the
        parent atomically. Deleting them separately first would be both
        redundant and — across two autocommit statements — interruptible,
        leaving a session with no messages or messages with no session.
        """
        cur = await self._conn.execute(
            "DELETE FROM chat_sessions WHERE id = ?", (session_id,)
        )
        await self._conn.commit()
        return bool(cur.rowcount)

    async def append_message(self, message: ChatMessage) -> None:
        await self._conn.execute(
            "INSERT INTO chat_messages "
            "(id, session_id, role, content, created_at, model, tokens_in, tokens_out) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message.id,
                message.session_id,
                message.role.value,
                message.content,
                _iso(message.created_at),
                message.model,
                message.tokens_in,
                message.tokens_out,
            ),
        )
        await self._conn.commit()

    async def list_messages(self, session_id: str) -> list[ChatMessage]:
        async with self._conn.execute(
            "SELECT id, session_id, role, content, created_at, model, tokens_in, tokens_out "
            "FROM chat_messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        result: list[ChatMessage] = []
        for row in rows:
            created_at = _parse_dt(row[4])
            assert created_at is not None
            result.append(
                ChatMessage(
                    id=row[0],
                    session_id=row[1],
                    role=ChatRole(row[2]),
                    content=row[3],
                    created_at=created_at,
                    model=row[5],
                    tokens_in=row[6],
                    tokens_out=row[7],
                )
            )
        return result

    async def list_sessions(self, backend_id: str | None = None) -> list[ChatSession]:
        if backend_id is None:
            query = "SELECT id, backend_id, title, created_at, updated_at, model FROM chat_sessions"
            params: tuple[str, ...] = ()
        else:
            query = (
                "SELECT id, backend_id, title, created_at, updated_at, model "
                "FROM chat_sessions WHERE backend_id = ?"
            )
            params = (backend_id,)
        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        result: list[ChatSession] = []
        for row in rows:
            created_at = _parse_dt(row[3])
            assert created_at is not None
            result.append(
                ChatSession(
                    id=row[0],
                    backend_id=row[1],
                    title=row[2],
                    created_at=created_at,
                    updated_at=_parse_dt(row[4]),
                    model=row[5],
                )
            )
        return result


class _SqliteOnboardingRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def get(self, onboarding_id: str) -> OnboardingState | None:
        async with self._conn.execute(
            "SELECT id, current_step, selected_backend_kind, created_backend_id, error "
            "FROM onboarding WHERE id = ?",
            (onboarding_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return OnboardingState(
            id=row[0],
            current_step=OnboardingStep(row[1]),
            selected_backend_kind=row[2],
            created_backend_id=row[3],
            error=row[4],
        )

    async def put(self, state: OnboardingState) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO onboarding "
            "(id, current_step, selected_backend_kind, created_backend_id, error) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                state.id,
                state.current_step.value,
                state.selected_backend_kind,
                state.created_backend_id,
                state.error,
            ),
        )
        await self._conn.commit()


class _SqliteUsageRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def put_snapshot(self, backend_id: str, windows: list[UsageWindow]) -> None:
        now = _iso(datetime.now(tz=UTC))
        for w in windows:
            await self._conn.execute(
                "INSERT INTO usage_snapshots "
                "(backend_id, window_type, usage_percent, tokens_used, tokens_limit, resets_at, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    backend_id,
                    w.window_type,
                    w.usage_percent,
                    w.tokens_used,
                    w.tokens_limit,
                    _iso(w.resets_at) if w.resets_at else None,
                    now,
                ),
            )
        await self._conn.commit()

    async def get_latest_snapshots(self, backend_id: str) -> list[UsageWindow]:
        async with self._conn.execute(
            "SELECT window_type, usage_percent, tokens_used, tokens_limit, resets_at, recorded_at "
            "FROM usage_snapshots WHERE backend_id = ? ORDER BY recorded_at DESC",
            (backend_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        seen: set[str] = set()
        result: list[UsageWindow] = []
        for row in rows:
            wtype = row[0]
            if wtype in seen:
                continue
            seen.add(wtype)
            result.append(
                UsageWindow(
                    window_type=wtype,
                    usage_percent=row[1],
                    tokens_used=row[2],
                    tokens_limit=row[3],
                    resets_at=_parse_dt(row[4]),
                )
            )
        return result

    async def set_rate_limited(self, backend_id: str, until: datetime, reason: str) -> None:
        await self._conn.execute(
            "UPDATE backends SET rate_limited_until = ?, rate_limit_reason = ? WHERE id = ?",
            (_iso(until), reason, backend_id),
        )
        await self._conn.commit()

    async def clear_rate_limited(self, backend_id: str) -> None:
        await self._conn.execute(
            "UPDATE backends SET rate_limited_until = NULL, rate_limit_reason = NULL WHERE id = ?",
            (backend_id,),
        )
        await self._conn.commit()

    async def get_rate_limit_state(self, backend_id: str) -> tuple[datetime | None, str | None]:
        async with self._conn.execute(
            "SELECT rate_limited_until, rate_limit_reason FROM backends WHERE id = ?",
            (backend_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return (None, None)
        return (_parse_dt(row[0]), row[1])

    async def set_last_used(self, backend_id: str, at: datetime) -> None:
        await self._conn.execute(
            "UPDATE backends SET last_used_at = ? WHERE id = ?",
            (_iso(at), backend_id),
        )
        await self._conn.commit()

    async def set_last_polled(self, backend_id: str, at: datetime) -> None:
        await self._conn.execute(
            "UPDATE backends SET last_polled_at = ? WHERE id = ?",
            (_iso(at), backend_id),
        )
        await self._conn.commit()

    async def set_chain(self, entries: list[FallbackChainEntry]) -> None:
        # The ONLY write here that spans more than one statement, and therefore
        # the only one that needs a transaction of its own now that the
        # connection is in autocommit (see _ensure_conn). Without this the
        # DELETE would commit on its own and a failure mid-loop would leave the
        # chain empty — a backend list that silently routes nowhere.
        #
        # IMMEDIATE takes the write lock up front instead of on first write, so
        # two concurrent set_chain callers queue on `busy_timeout` rather than
        # one of them failing partway with SQLITE_BUSY after already deleting.
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            await self._conn.execute("DELETE FROM fallback_chains")
            for entry in entries:
                await self._conn.execute(
                    "INSERT INTO fallback_chains (backend_id, priority) VALUES (?, ?)",
                    (entry.backend_id, entry.priority),
                )
        except BaseException:
            await self._conn.execute("ROLLBACK")
            raise
        await self._conn.execute("COMMIT")

    async def get_chain(self) -> list[FallbackChainEntry]:
        async with self._conn.execute(
            "SELECT backend_id, priority FROM fallback_chains ORDER BY priority"
        ) as cursor:
            rows = await cursor.fetchall()
        return [FallbackChainEntry(backend_id=row[0], priority=row[1]) for row in rows]


class SqliteStorage:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    #: How long a writer waits for the write lock before giving up.
    #:
    #: WAL lets readers and one writer proceed concurrently, but it does NOT
    #: serialise two writers — the second gets SQLITE_BUSY. Python's default
    #: timeout is 5 s, and a connection that hits it raises
    #: ``OperationalError: database is locked`` immediately instead of queueing.
    #:
    #: That is not hypothetical. Downstream (HypePaper, 2026-07-27) it failed
    #: 2,295 of 2,701 result-extraction runs — 85% — with exactly that message,
    #: because each run holds a write transaction across a multi-second LLM
    #: round-trip while other passes write chat/usage rows to the same per-user
    #: DB. Reproduced here: 3 concurrent writers against a 6 s holder give 3/3
    #: failures at the default and 0/3 with this pragma.
    #:
    #: 30 s comfortably covers an LLM call; a genuine deadlock still surfaces,
    #: just 6× later.
    BUSY_TIMEOUT_MS = 30_000

    async def _ensure_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            # timeout= governs the C-level lock wait; busy_timeout is the SQLite
            # pragma. Set BOTH — the pragma alone can be reset by a later
            # connection-level default, and the kwarg alone does not apply to
            # statements issued after a schema change.
            # isolation_level=None => AUTOCOMMIT, and this is the actual fix for
            # "database is locked" rather than a longer wait.
            #
            # python-sqlite3 defaults to opening an implicit transaction on the
            # first write and holding it until commit(). Every repo method here
            # is `execute(...)` then `commit()`, so under normal use that window
            # is microseconds — but the caller runs these DURING a provider
            # round-trip, and any await between the two pins the single WAL
            # writer for the whole call. That is what BUSY_TIMEOUT_MS was raised
            # to paper over, and why its docstring says "30 s comfortably covers
            # an LLM call": it does not. Measured 2026-08-08 against HypePaper's
            # deep-analysis worker, whose calls run 80 s+ — concurrent workers
            # got `OperationalError: database is locked` and the calls FAILED
            # BEFORE reaching the provider, so raising concurrency reduced
            # throughput (48 slots produced literally zero completions).
            #
            # In autocommit each write lands and releases immediately, so no
            # await can sit inside a write transaction. The one genuinely
            # multi-statement write (`set_chain`) opens an explicit transaction.
            self._conn = await aiosqlite.connect(
                self._path,
                timeout=self.BUSY_TIMEOUT_MS / 1000,
                isolation_level=None,
            )
            await self._conn.execute("PRAGMA journal_mode = WAL")
            await self._conn.execute(f"PRAGMA busy_timeout = {self.BUSY_TIMEOUT_MS}")
            await self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    async def migrate(self) -> None:
        """Bring the database up to the current schema version.

        Delegates to the versioned migrations module. Fresh databases get the
        full baseline schema in one shot; existing databases at an older
        version get each pending migration applied in order. This replaces
        the earlier ``CREATE TABLE IF NOT EXISTS``-only approach that
        silently left pre-existing tables with out-of-date columns (see the
        pre-0.3.0 rate-limit-columns backfill that had to be hand-rolled
        downstream).
        """
        conn = await self._ensure_conn()
        await apply_migrations(conn, baseline_schema=_SCHEMA)

    async def backends(self) -> BackendRepository:
        return _SqliteBackendRepo(await self._ensure_conn())

    async def sessions(self) -> SessionRepository:
        return _SqliteSessionRepo(await self._ensure_conn())

    async def history(self) -> HistoryRepository:
        return _SqliteHistoryRepo(await self._ensure_conn())

    async def onboarding(self) -> OnboardingRepository:
        return _SqliteOnboardingRepo(await self._ensure_conn())

    async def usage(self) -> UsageRepository:
        return _SqliteUsageRepo(await self._ensure_conn())

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
