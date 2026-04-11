from __future__ import annotations

import builtins
from collections.abc import Mapping
from datetime import UTC, datetime

from ai_accounts_core.domain.backend import (
    Backend,
    BackendCredential,
    BackendStatus,
    DetectResult,
)
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.backend import BackendProtocol, LoginFlow, Model
from ai_accounts_core.protocols.storage import StorageProtocol
from ai_accounts_core.protocols.vault import VaultProtocol

from .errors import (
    BackendKindUnknown,
    BackendNotFound,
    BackendNotReady,
    BackendValidationFailed,
    CredentialMissing,
)


def _now() -> datetime:
    return datetime.now(UTC)


_SENTINEL: object = object()


class AccountService:
    def __init__(
        self,
        *,
        storage: StorageProtocol,
        vault: VaultProtocol,
        backends: Mapping[str, BackendProtocol],
    ) -> None:
        self._storage = storage
        self._vault = vault
        self._backend_impls: dict[str, BackendProtocol] = dict(backends)

    async def create(
        self,
        kind: str,
        *,
        display_name: str,
        config: dict[str, object] | None = None,
    ) -> Backend:
        if kind not in self._backend_impls:
            raise BackendKindUnknown(f"unknown backend kind: {kind}")
        backend = Backend(
            id=new_id("bkd"),
            kind=kind,
            display_name=display_name,
            config=config or {},
            status=BackendStatus.UNCONFIGURED,
            created_at=_now(),
        )
        repo = await self._storage.backends()
        await repo.create(backend)
        return backend

    async def get(self, backend_id: str) -> Backend:
        repo = await self._storage.backends()
        backend = await repo.get(backend_id)
        if backend is None:
            raise BackendNotFound(backend_id)
        return backend

    async def list(self) -> list[Backend]:
        repo = await self._storage.backends()
        return await repo.list()

    async def delete(self, backend_id: str) -> None:
        backend = await self.get(backend_id)  # raises BackendNotFound
        repo = await self._storage.backends()
        await repo.delete(backend.id)

    async def detect(self, backend_id: str) -> DetectResult:
        backend = await self.get(backend_id)
        impl = self._backend_impls[backend.kind]
        result = await impl.detect()
        if not result.installed:
            await self._update_status(
                backend, BackendStatus.NEEDS_LOGIN, last_error="CLI not installed"
            )
        return result

    async def login(
        self, backend_id: str, *, flow_kind: str, inputs: dict[str, str]
    ) -> Backend:
        backend = await self.get(backend_id)
        impl = self._backend_impls[backend.kind]
        plaintext = await impl.login(LoginFlow(kind=flow_kind, inputs=inputs))

        ciphertext = await self._vault.encrypt(
            plaintext, context={"backend_id": backend_id}
        )
        key_id = await self._vault.current_key_id()
        credential = BackendCredential(
            id=new_id("crd"),
            backend_id=backend_id,
            ciphertext=ciphertext,
            key_id=key_id,
            created_at=_now(),
        )
        repo = await self._storage.backends()
        await repo.put_credential(credential)
        return await self._update_status(backend, BackendStatus.VALIDATING)

    async def validate(self, backend_id: str) -> Backend:
        backend = await self.get(backend_id)
        impl = self._backend_impls[backend.kind]
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend_id)
        if stored is None:
            raise CredentialMissing(backend_id)
        plaintext = await self._vault.decrypt(
            stored.ciphertext, context={"backend_id": backend_id}
        )
        ok = await impl.validate(plaintext)
        if not ok:
            await self._update_status(
                backend, BackendStatus.ERROR, last_error="validation failed"
            )
            raise BackendValidationFailed(backend_id)
        return await self._update_status(backend, BackendStatus.READY, last_error=None)

    async def list_models(self, backend_id: str) -> builtins.list[Model]:
        backend = await self.get(backend_id)
        if backend.status is not BackendStatus.READY:
            raise BackendNotReady(backend_id)
        impl = self._backend_impls[backend.kind]
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend_id)
        if stored is None:
            raise CredentialMissing(backend_id)
        plaintext = await self._vault.decrypt(
            stored.ciphertext, context={"backend_id": backend_id}
        )
        return await impl.list_models(plaintext)

    async def _update_status(
        self,
        backend: Backend,
        status: BackendStatus,
        *,
        last_error: str | None | object = _SENTINEL,
    ) -> Backend:
        new_error = backend.last_error if last_error is _SENTINEL else last_error
        updated = Backend(
            id=backend.id,
            kind=backend.kind,
            display_name=backend.display_name,
            config=backend.config,
            status=status,
            created_at=backend.created_at,
            updated_at=_now(),
            last_error=new_error,  # type: ignore[arg-type]
        )
        repo = await self._storage.backends()
        await repo.update(updated)
        return updated
