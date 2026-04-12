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
    StorageProtocol,
    UsageRepository,
)

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()
_CURRENT_VERSION = 1


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
            query = (
                "SELECT id, backend_id, title, created_at, updated_at, model "
                "FROM chat_sessions"
            )
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
        await self._conn.execute("DELETE FROM fallback_chains")
        for entry in entries:
            await self._conn.execute(
                "INSERT INTO fallback_chains (backend_id, priority) VALUES (?, ?)",
                (entry.backend_id, entry.priority),
            )
        await self._conn.commit()

    async def get_chain(self) -> list[FallbackChainEntry]:
        async with self._conn.execute(
            "SELECT backend_id, priority FROM fallback_chains ORDER BY priority"
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            FallbackChainEntry(backend_id=row[0], priority=row[1]) for row in rows
        ]


class SqliteStorage:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def _ensure_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._path)
            await self._conn.execute("PRAGMA journal_mode = WAL")
            await self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    async def migrate(self) -> None:
        conn = await self._ensure_conn()
        await conn.executescript(_SCHEMA)
        async with conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version") as cur:
            row = await cur.fetchone()
        current = row[0] if row else 0
        if current < _CURRENT_VERSION:
            await conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (_CURRENT_VERSION,)
            )
            await conn.commit()

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
