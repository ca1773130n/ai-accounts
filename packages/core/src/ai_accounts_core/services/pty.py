from __future__ import annotations

from datetime import UTC, datetime

from ai_accounts_core.domain.session import LiveSession, SessionKind, SessionState
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.backend import PtyHandle, PtyRequest
from ai_accounts_core.protocols.storage import StorageProtocol
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import CredentialMissing


class PtyService:
    def __init__(
        self,
        *,
        account_service: AccountService,
        storage: StorageProtocol,
    ) -> None:
        self._account_service = account_service
        self._storage = storage
        self._handles: dict[str, PtyHandle] = {}

    async def spawn(
        self,
        *,
        backend_id: str,
        command: tuple[str, ...],
        cols: int = 80,
        rows: int = 24,
        env: dict[str, str] | None = None,
    ) -> tuple[str, PtyHandle]:
        backend = await self._account_service.get(backend_id)
        impl = self._account_service._impl_for(backend.kind)
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend.id)
        if stored is None:
            raise CredentialMissing(backend.id)
        plaintext = await self._account_service._vault.decrypt(
            stored.ciphertext, context={"backend_id": backend.id}
        )
        request = PtyRequest(command=command, cols=cols, rows=rows, env=env or {})
        isolation_dir = self._account_service._isolation_dir(backend.id)
        handle = await impl.pty(request, plaintext, isolation_dir=isolation_dir)

        session_id = new_id("pty")
        now = datetime.now(UTC)
        live = LiveSession(
            id=session_id,
            kind=SessionKind.PTY,
            backend_id=backend_id,
            state=SessionState.ACTIVE,
            started_at=now,
            last_seen_at=now,
        )
        session_repo = await self._storage.sessions()
        await session_repo.upsert(live)
        self._handles[session_id] = handle
        return session_id, handle

    def attach(self, session_id: str) -> PtyHandle | None:
        return self._handles.get(session_id)

    async def kill(self, session_id: str) -> None:
        handle = self._handles.pop(session_id, None)
        if handle:
            await handle.close()
        session_repo = await self._storage.sessions()
        await session_repo.end(session_id)
