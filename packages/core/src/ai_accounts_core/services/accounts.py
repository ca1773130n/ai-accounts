from __future__ import annotations

import builtins
import logging
import os
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ai_accounts_core.domain.backend import (
    Backend,
    BackendCredential,
    BackendStatus,
    DetectResult,
)
from ai_accounts_core.ids import new_id
from ai_accounts_core.login import LoginSession
from ai_accounts_core.login.registry import LoginSessionRegistry
from ai_accounts_core.protocols.backend import BackendProtocol, Model
from ai_accounts_core.protocols.storage import StorageProtocol
from ai_accounts_core.protocols.vault import VaultProtocol

from .errors import (
    BackendKindUnknown,
    BackendNotFound,
    BackendNotReady,
    BackendValidationFailed,
    CredentialMissing,
    LoginFlowUnsupported,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


_SENTINEL: object = object()


def _as_str(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


class ConfigPathOutsideAllowedRoots(ValueError):
    """Raised when a caller supplies a ``config_path`` that resolves outside
    the user's home directory and the per-backend isolation tree.  The
    backend then can read or create CLI state at an operator-controlled
    location, which we treat as a security issue and refuse at the service
    boundary."""


def _resolve_config_path_strict(
    raw: object, *, allowed_roots: tuple[Path, ...]
) -> Path | None:
    """Validate a user-supplied ``config_path`` and return a resolved ``Path``.

    ``raw`` may be ``None`` / empty (we skip validation and return ``None``).
    When a value is supplied it must, after ``~`` expansion and
    ``Path.resolve()``, be contained in one of ``allowed_roots``; otherwise
    :class:`ConfigPathOutsideAllowedRoots` is raised.  Symlinks are
    followed by ``resolve()`` so this blocks the ``~/x -> /etc`` trick too.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    expanded = Path(os.path.expanduser(s))
    try:
        resolved = expanded.resolve()
    except (OSError, RuntimeError) as exc:  # pragma: no cover — filesystem-dependent
        raise ConfigPathOutsideAllowedRoots(
            f"config_path {s!r} could not be resolved: {exc}"
        ) from exc
    roots = tuple(r.resolve() for r in allowed_roots)
    if not any(
        resolved == root or resolved.is_relative_to(root) for root in roots
    ):
        raise ConfigPathOutsideAllowedRoots(
            f"config_path {s!r} resolves to {resolved} which is outside "
            f"the allowed roots {[str(r) for r in roots]}"
        )
    return resolved


class AccountService:
    def __init__(
        self,
        *,
        storage: StorageProtocol,
        vault: VaultProtocol,
        backends: Mapping[str, BackendProtocol],
        isolation_base_dir: Path,
        login_registry: LoginSessionRegistry | None = None,
    ) -> None:
        self._storage = storage
        self._vault = vault
        self._backend_impls: dict[str, BackendProtocol] = dict(backends)
        self._isolation_base_dir = Path(isolation_base_dir)
        self._isolation_base_dir.mkdir(parents=True, exist_ok=True)
        self._login_registry = login_registry or LoginSessionRegistry()

    @property
    def login_registry(self) -> LoginSessionRegistry:
        return self._login_registry

    def available_kinds(self) -> builtins.list[str]:
        return sorted(self._backend_impls.keys())

    def _impl_for(self, kind: str) -> BackendProtocol:
        return self._backend_impls[kind]

    def _isolation_dir(self, backend_id: str) -> Path:
        return self._isolation_base_dir / backend_id

    def _allowed_config_roots(self) -> tuple[Path, ...]:
        """Roots under which a ``config_path`` is allowed to resolve.

        The per-backend isolation dir is always a subdirectory of
        ``_isolation_base_dir``, so we don't need to enumerate it here —
        validating against the base and the user's home is enough.
        """
        return (
            Path.home().resolve(),
            self._isolation_base_dir.resolve(),
        )

    def _validate_config(self, config: dict[str, object]) -> None:
        """Validate untrusted config keys at the service boundary.

        Currently only enforces that ``config_path``, if supplied, resolves
        under the user's home directory or the isolation tree.  Raises
        :class:`ConfigPathOutsideAllowedRoots` on violation.
        """
        if "config_path" in config:
            _resolve_config_path_strict(
                config.get("config_path"),
                allowed_roots=self._allowed_config_roots(),
            )

    async def _resolve_config_dir(self, backend_id: str) -> Path:
        """Resolve the CLI config directory for a backend.

        If the backend's config has a config_path, use that (it's where
        the CLI stored credentials during login). Otherwise fall back to
        the isolation dir.  Any ``config_path`` is validated against the
        allowed roots even when it was written directly to storage — so a
        tampered DB row can't force the server to read from an arbitrary
        location.
        """
        backend = await self.get(backend_id)
        raw = backend.config.get("config_path")
        resolved = _resolve_config_path_strict(
            raw, allowed_roots=self._allowed_config_roots()
        )
        if resolved is not None:
            resolved.mkdir(parents=True, exist_ok=True)
            return resolved
        base = self._isolation_base_dir / backend_id
        base.mkdir(parents=True, exist_ok=True)
        return base

    def config_dir(self, backend_id: str) -> Path:
        """Public accessor for a backend's base isolation directory.

        For the resolved config dir (respecting config_path), use
        _resolve_config_dir() which is async.
        """
        return self._isolation_base_dir / backend_id

    async def create(
        self,
        kind: str,
        *,
        display_name: str,
        config: dict[str, object] | None = None,
    ) -> Backend:
        if kind not in self._backend_impls:
            raise BackendKindUnknown(f"unknown backend kind: {kind}")
        cfg: dict[str, object] = dict(config or {})
        self._validate_config(cfg)

        # Dedup: if a backend row already exists for this (kind, config_path)
        # pair (or (kind, email) for backends with no config_path), update it
        # in place instead of creating a second row. Wizards that re-run the
        # "Add Account" flow for the same underlying credentials should not
        # accumulate duplicates.
        existing = await self._find_matching_backend(kind, cfg)
        if existing is not None:
            merged_cfg = dict(existing.config)
            merged_cfg.update(cfg)
            return await self.update(
                existing.id,
                display_name=display_name,
                config=merged_cfg,
            )

        backend = Backend(
            id=new_id("bkd"),
            kind=kind,
            display_name=display_name,
            config=cfg,
            status=BackendStatus.UNCONFIGURED,
            created_at=_now(),
        )
        repo = await self._storage.backends()
        await repo.create(backend)
        self._isolation_dir(backend.id).mkdir(parents=True, exist_ok=True)
        return backend

    async def _find_matching_backend(
        self, kind: str, config: dict[str, object]
    ) -> Backend | None:
        """Return an existing backend row that represents the same underlying
        account, or None. Match key:
          - (kind, config_path) when config_path is set (CLI-managed creds)
          - (kind, api_key_env) when api_key_env is set (API-key flows)
          - (kind, email) as a last resort
        """
        config_path = _as_str(config.get("config_path"))
        api_key_env = _as_str(config.get("api_key_env"))
        email = _as_str(config.get("email"))
        if not (config_path or api_key_env or email):
            return None
        repo = await self._storage.backends()
        existing = await repo.list()
        for b in existing:
            if b.kind != kind:
                continue
            b_path = _as_str(b.config.get("config_path"))
            b_env = _as_str(b.config.get("api_key_env"))
            b_email = _as_str(b.config.get("email"))
            if config_path and b_path and config_path == b_path:
                return b
            if api_key_env and b_env and api_key_env == b_env:
                return b
            if email and b_email and email == b_email and not (
                config_path or api_key_env or b_path or b_env
            ):
                return b
        return None

    async def get(self, backend_id: str) -> Backend:
        repo = await self._storage.backends()
        backend = await repo.get(backend_id)
        if backend is None:
            raise BackendNotFound(backend_id)
        return backend

    async def list(self) -> builtins.list[Backend]:
        repo = await self._storage.backends()
        return await repo.list()

    async def update(
        self,
        backend_id: str,
        *,
        display_name: str | None = None,
        config: dict[str, object] | None | object = _SENTINEL,
    ) -> Backend:
        """Patch a backend's display_name and/or config.

        Unspecified kwargs are left unchanged. Pass `config=None` to clear,
        or `config={...}` to replace (merge is caller's responsibility —
        pass the full new dict).
        """
        backend = await self.get(backend_id)
        new_display = display_name if display_name is not None else backend.display_name
        if config is _SENTINEL:
            new_config = backend.config
        else:
            new_config = config if config is not None else {}
            if isinstance(new_config, dict):
                self._validate_config(new_config)
        updated = Backend(
            id=backend.id,
            kind=backend.kind,
            display_name=new_display,
            config=new_config,  # type: ignore[arg-type]
            status=backend.status,
            created_at=backend.created_at,
            updated_at=_now(),
            last_error=backend.last_error,
        )
        repo = await self._storage.backends()
        await repo.update(updated)
        return updated

    async def delete(self, backend_id: str) -> None:
        backend = await self.get(backend_id)
        repo = await self._storage.backends()
        await repo.delete(backend.id)
        isolation_dir = self._isolation_dir(backend.id)
        if isolation_dir.exists():
            try:
                shutil.rmtree(isolation_dir)
            except OSError as exc:
                # Closes SILENT-FAILURES.md H-04: previously
                # `ignore_errors=True` masked permission/filesystem problems
                # so operators never noticed stale credential directories
                # lingering on disk.
                logger.warning(
                    "failed to delete isolation dir %s: %s", isolation_dir, exc
                )

    async def detect(self, backend_id: str) -> DetectResult:
        backend = await self.get(backend_id)
        impl = self._backend_impls[backend.kind]
        result = await impl.detect()
        if not result.installed:
            await self._update_status(
                backend, BackendStatus.NEEDS_LOGIN, last_error="CLI not installed"
            )
        return result

    async def begin_login(
        self,
        backend_id: str,
        *,
        flow_kind: str,
        inputs: dict[str, str],
    ) -> LoginSession:
        logger.info("begin_login: account=%s flow=%s", backend_id, flow_kind)
        backend = await self.get(backend_id)
        impl = self._backend_impls.get(backend.kind)
        if impl is None:
            raise BackendKindUnknown(f"backend kind '{backend.kind}' not registered")
        if flow_kind not in impl.supported_login_flows:
            raise LoginFlowUnsupported(
                f"{backend.kind} does not support flow {flow_kind!r}; "
                f"supported: {sorted(impl.supported_login_flows)}"
            )
        isolation_dir = self._isolation_dir(backend_id)
        isolation_dir.mkdir(parents=True, exist_ok=True)
        session = impl.begin_login(
            flow_kind=flow_kind,
            config=dict(backend.config),
            vault_ctx={"backend_id": backend_id, "kind": backend.kind},
            isolation_dir=isolation_dir,
        )
        await self._login_registry.register(session, backend_id=backend_id)
        logger.info(
            "begin_login: session registered sid=%s backend_id=%s",
            session.session_id,
            backend_id,
        )
        return session

    async def store_credential(
        self, backend_id: str, credential: bytes
    ) -> Backend:
        """Persist an encrypted credential for backend_id and mark it VALIDATING."""
        backend = await self.get(backend_id)
        ciphertext = await self._vault.encrypt(
            credential, context={"backend_id": backend.id}
        )
        key_id = await self._vault.current_key_id()
        cred = BackendCredential(
            id=new_id("crd"),
            backend_id=backend.id,
            ciphertext=ciphertext,
            key_id=key_id,
            created_at=_now(),
        )
        repo = await self._storage.backends()
        await repo.put_credential(cred)
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
        config_dir = await self._resolve_config_dir(backend_id)
        ok = await impl.validate(plaintext, isolation_dir=config_dir)
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
        isolation_dir = await self._resolve_config_dir(backend_id)
        return await impl.list_models(plaintext, isolation_dir=isolation_dir)

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
