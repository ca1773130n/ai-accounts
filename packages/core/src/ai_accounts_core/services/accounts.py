from __future__ import annotations

import builtins
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_accounts_core.services.discovery import DiscoveredConfig
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
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.ids import new_id
from ai_accounts_core.login import LoginSession
from ai_accounts_core.login.registry import LoginSessionRegistry
from ai_accounts_core.protocols.backend import BackendProtocol, ChatRequest, Model
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

# Cheapest model per backend kind for keep-alive / scheduled pings. A
# keep-alive only needs to exercise the auth-refresh path, so we use the
# smallest model to minimise quota burn — on Claude (Claude Code), the
# default would otherwise be Sonnet/Opus. Kinds absent here fall back to the
# backend's configured model (or "default").
_KEEP_ALIVE_MODELS: dict[str, str] = {
    "claude": "claude-haiku-4-5-20251001",
}


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


def _resolve_config_path_strict(raw: object, *, allowed_roots: tuple[Path, ...]) -> Path | None:
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
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
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

    async def discover_existing(
        self, *, probe_timeout: float = 12.0
    ) -> builtins.list[DiscoveredConfig]:
        """Auto-detect CLI config directories the user already authenticated.

        Globs ``~/.<kind>*`` for every registered backend kind and runs a
        small non-interactive prompt against each candidate to verify the
        directory is actually logged in. Used by the UI to:

          1. Surface NEW candidates for one-click import.
          2. Re-check ALREADY-IMPORTED accounts so a stale "ready" status
             (e.g. an OAuth token that expired since the last validate()
             call) surfaces immediately.

        For each imported path, the matching backend row's status is
        synced to the probe result (ready ↔ error) before returning, so
        the caller's next ``list()`` reflects reality.
        """
        # Lazy import — keeps the service module light when discovery isn't used.
        from ai_accounts_core.services.discovery import (
            DiscoveredConfig,
            discover_all,
        )

        found = await discover_all(self.available_kinds(), probe_timeout=probe_timeout)
        # Build path → backend lookup so we can annotate + sync status.
        path_to_backend: dict[str, Backend] = {}
        for b in await self.list():
            cfg_path = b.config.get("config_path")
            if cfg_path:
                resolved = str(Path(str(cfg_path)).expanduser().resolve())
                path_to_backend[resolved] = b

        enriched: builtins.list[DiscoveredConfig] = []
        for c in found:
            resolved = str(Path(c.path).expanduser().resolve())
            backend = path_to_backend.get(resolved)
            if backend is None:
                enriched.append(c)
                continue
            if backend.kind != c.kind:
                # A different kind's home glob matched this row's dir (e.g.
                # claude's ".claude*" catching a claude_custom config_path).
                # The probe ran as the WRONG kind — its verdict says nothing
                # about this account, and the dir is already owned, so don't
                # sync status or surface it as importable.
                continue
            # Already imported — sync the backend's status to the probe
            # result. The probe is a real prompt (claude -p hello, etc.),
            # so it catches expired tokens that the file-probe validate()
            # would miss on macOS.
            #
            # EXCEPT on probe timeout: a slow CLI is no evidence the login
            # is dead. Downgrading READY → ERROR on timeout knocked valid
            # backends out of scheduler.pick() until the next validate()
            # ("No ai-accounts backend available" downstream).
            probe_timed_out = c.error is not None and c.error.startswith("probe timed out")
            if probe_timed_out and not c.is_logged_in and backend.status == BackendStatus.READY:
                logger.info(
                    "discovery: probe timed out for %s — keeping READY (inconclusive)",
                    backend.id,
                )
                enriched.append(
                    DiscoveredConfig(
                        kind=c.kind,
                        path=c.path,
                        suggested_name=c.suggested_name,
                        is_logged_in=True,  # reflect the row we trust
                        error=c.error,
                        backend_id=backend.id,
                    )
                )
                continue
            new_status = BackendStatus.READY if c.is_logged_in else BackendStatus.ERROR
            if backend.status != new_status:
                logger.info(
                    "discovery: syncing %s status %s → %s",
                    backend.id,
                    backend.status,
                    new_status,
                )
                backend = await self._update_status(backend, new_status)
            enriched.append(
                DiscoveredConfig(
                    kind=c.kind,
                    path=c.path,
                    suggested_name=c.suggested_name,
                    is_logged_in=c.is_logged_in,
                    error=c.error,
                    backend_id=backend.id,
                )
            )
        return enriched

    async def import_discovered(
        self,
        kind: str,
        config_path: str,
        *,
        display_name: str | None = None,
    ) -> Backend:
        """Create a backend row pointing at an existing CLI config directory.

        Stores an empty credential (CLI-browser flow shape — the CLI owns
        the auth in its config dir) and runs validate to flip the status
        to READY (or ERROR). Reuses AccountService.create's dedup logic.
        """
        cfg: dict[str, object] = {"config_path": config_path}
        backend = await self.create(
            kind,
            display_name=display_name or config_path.split("/")[-1],
            config=cfg,
        )
        await self.store_credential(backend.id, b"")
        try:
            return await self.validate(backend.id)
        except Exception:
            # validate raises BackendValidationFailed on a non-ready backend;
            # the row exists with status=error, which is fine for the UI to
            # surface. Re-fetch so the caller sees the actual final status.
            return await self.get(backend.id)

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
        resolved = _resolve_config_path_strict(raw, allowed_roots=self._allowed_config_roots())
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

    async def _find_matching_backend(self, kind: str, config: dict[str, object]) -> Backend | None:
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
            if (
                email
                and b_email
                and email == b_email
                and not (config_path or api_key_env or b_path or b_env)
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
            # `config` is typed `object` only so the _SENTINEL default can sit
            # alongside dict/None; narrow it back here. None (clear) and any
            # non-dict misuse both collapse to an empty config, as before.
            new_config = config if isinstance(config, dict) else {}
            self._validate_config(new_config)
        updated = Backend(
            id=backend.id,
            kind=backend.kind,
            display_name=new_display,
            config=new_config,
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
                logger.warning("failed to delete isolation dir %s: %s", isolation_dir, exc)

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

    async def store_credential(self, backend_id: str, credential: bytes) -> Backend:
        """Persist an encrypted credential for backend_id and mark it VALIDATING."""
        backend = await self.get(backend_id)
        ciphertext = await self._vault.encrypt(credential, context={"backend_id": backend.id})
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
        plaintext = await self._vault.decrypt(stored.ciphertext, context={"backend_id": backend_id})
        config_dir = await self._resolve_config_dir(backend_id)
        ok = await impl.validate(plaintext, isolation_dir=config_dir)
        if not ok:
            await self._update_status(backend, BackendStatus.ERROR, last_error="validation failed")
            raise BackendValidationFailed(backend_id)
        return await self._update_status(backend, BackendStatus.READY, last_error=None)

    async def keep_alive(self, backend_id: str) -> bool:
        """Send a minimal throwaway turn to keep the backend's auth fresh.

        ``validate()`` only probes for credential *presence* — it never
        makes an authenticated call, so it cannot refresh an OAuth access
        token. CLI/cliproxy-backed kinds (Claude, Codex, Antigravity, OpenCode)
        refresh their short-lived access token **only when they actually
        invoke the provider**, using the long-lived refresh token. A
        long-idle account's access token therefore expires silently and the
        next real chat 401s ("all accounts exhausted").

        This drives one tiny ``impl.chat`` (a single "hi", ``max_tokens=1``)
        which exercises that refresh-on-use path. It deliberately does NOT
        create a ChatSession or persist any message, so it leaves no trace
        in the user's chat history.

        Returns ``True`` when the call completed cleanly. On failure it flips
        the backend to ``ERROR`` (so the UI surfaces "needs re-login") and
        returns ``False``. A clean call on a previously non-READY backend
        promotes it back to ``READY`` — so keep-alive doubles as recovery
        for an account whose token had lapsed but whose refresh token is
        still valid.
        """
        backend = await self.get(backend_id)
        impl = self._impl_for(backend.kind)
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend_id)
        if stored is None:
            logger.info("keep_alive: %s has no stored credential — skipping", backend_id)
            return False
        plaintext = await self._vault.decrypt(stored.ciphertext, context={"backend_id": backend_id})
        config_dir = await self._resolve_config_dir(backend_id)

        probe = ChatMessage(
            id=new_id("msg"),
            session_id="keepalive",
            role=ChatRole.USER,
            content="hi",
            created_at=_now(),
        )
        # Use the cheapest model for the kind (Haiku for Claude Code) so the
        # 2-hourly keep-alive doesn't burn Sonnet/Opus quota.
        keep_alive_model = str(
            _KEEP_ALIVE_MODELS.get(backend.kind) or backend.config.get("model") or "default"
        )
        request = ChatRequest(
            messages=(probe,),
            model=keep_alive_model,
            params={"max_tokens": 1},
        )

        saw_error: str | None = None
        try:
            async for event in impl.chat(request, plaintext, isolation_dir=config_dir):
                if event.kind == "error":
                    saw_error = str(event.payload)[:300] if event.payload else "chat error"
        except Exception as exc:  # noqa: BLE001 — any failure means "not healthy"
            saw_error = f"keep-alive failed: {exc}"[:300]

        if saw_error is not None:
            logger.info("keep_alive: %s unhealthy — %s", backend_id, saw_error)
            await self._update_status(backend, BackendStatus.ERROR, last_error=saw_error)
            return False

        if backend.status is not BackendStatus.READY:
            await self._update_status(backend, BackendStatus.READY, last_error=None)
        return True

    async def list_models(self, backend_id: str) -> builtins.list[Model]:
        backend = await self.get(backend_id)
        if backend.status is not BackendStatus.READY:
            raise BackendNotReady(backend_id)
        impl = self._backend_impls[backend.kind]
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend_id)
        if stored is None:
            raise CredentialMissing(backend_id)
        plaintext = await self._vault.decrypt(stored.ciphertext, context={"backend_id": backend_id})
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
