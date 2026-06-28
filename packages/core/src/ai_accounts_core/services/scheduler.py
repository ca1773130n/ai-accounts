from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from ai_accounts_core.domain.backend import BackendStatus
from ai_accounts_core.domain.usage import (
    AccountHealth,
    FallbackChainEntry,
    PickResult,
)
from ai_accounts_core.protocols.storage import StorageProtocol
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import BackendNotFound

logger = logging.getLogger(__name__)

RATE_LIMIT_THRESHOLD = 95.0  # usage_percent above this = skip account


class AccountScheduler:
    def __init__(
        self,
        *,
        account_service: AccountService,
        storage: StorageProtocol,
        poll_interval_seconds: float = 60.0,
    ) -> None:
        self._accounts = account_service
        self._storage = storage
        self.poll_interval_seconds = poll_interval_seconds

    # ── Scheduling ──

    async def pick(self, kind: str | None = None) -> PickResult | None:
        chain = await self.get_chain()
        has_configured_chain = bool(chain)

        if kind:
            filtered = []
            for e in chain:
                try:
                    b = await self._accounts.get(e.backend_id)
                    if b.kind == kind:
                        filtered.append(e)
                except BackendNotFound:
                    logger.info(
                        "chain entry references missing backend %s, skipping",
                        e.backend_id,
                    )
            chain = filtered

        # Only fall back to all backends if NO chain was ever configured.
        # If a chain exists but the kind filter emptied it, return None
        # (the requested kind was intentionally excluded from the chain).
        if not chain and not has_configured_chain:
            backends = await self._accounts.list()
            chain = [
                FallbackChainEntry(backend_id=b.id, priority=i)
                for i, b in enumerate(backends)
                if b.status == BackendStatus.READY and (kind is None or b.kind == kind)
            ]

        now = datetime.now(UTC)
        best: FallbackChainEntry | None = None
        best_score = 999.0
        earliest_reset: datetime | None = None

        for entry in sorted(chain, key=lambda e: e.priority):
            health = await self.get_health(entry.backend_id)

            # Skip rate-limited accounts
            if health.rate_limited_until and health.rate_limited_until > now:
                if earliest_reset is None or health.rate_limited_until < earliest_reset:
                    earliest_reset = health.rate_limited_until
                logger.debug("pick: skipping %s (rate-limited)", entry.backend_id)
                continue

            # Skip accounts with any window above threshold
            max_usage = max((w.usage_percent for w in health.windows), default=0.0)
            if max_usage >= RATE_LIMIT_THRESHOLD:
                for w in health.windows:
                    if (
                        w.usage_percent >= RATE_LIMIT_THRESHOLD
                        and w.resets_at
                        and (earliest_reset is None or w.resets_at < earliest_reset)
                    ):
                        earliest_reset = w.resets_at
                logger.debug(
                    "pick: skipping %s (usage %.1f%% >= threshold)",
                    entry.backend_id,
                    max_usage,
                )
                continue

            if max_usage < best_score:
                best_score = max_usage
                best = entry

        if best is None:
            logger.info(
                "pick(kind=%s): all accounts exhausted, earliest_reset=%s",
                kind,
                earliest_reset,
            )
            return None

        # Resolve credential
        backend = await self._accounts.get(best.backend_id)
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend.id)
        if stored is None:
            logger.warning(
                "pick: best backend %s has no credential — needs re-authentication",
                backend.id,
            )
            return None
        plaintext = await self._accounts._vault.decrypt(
            stored.ciphertext, context={"backend_id": backend.id}
        )

        # Mark as used
        await self.mark_used(best.backend_id)

        return PickResult(
            backend_id=best.backend_id,
            kind=backend.kind,
            credential=plaintext,
            isolation_dir=str(self._accounts._isolation_dir(backend.id)),
            retry_after=earliest_reset,
        )

    # ── Priority Chain ──

    async def set_chain(self, entries: list[FallbackChainEntry]) -> None:
        usage_repo = await self._storage.usage()
        await usage_repo.set_chain(entries)

    async def get_chain(self) -> list[FallbackChainEntry]:
        usage_repo = await self._storage.usage()
        return await usage_repo.get_chain()

    # ── Health ──

    async def get_health(self, backend_id: str) -> AccountHealth:
        backend = await self._accounts.get(backend_id)
        usage_repo = await self._storage.usage()
        windows = await usage_repo.get_latest_snapshots(backend_id)
        rate_limited_until, rate_limit_reason = await usage_repo.get_rate_limit_state(backend_id)
        return AccountHealth(
            backend_id=backend_id,
            kind=backend.kind,
            windows=tuple(windows),
            rate_limited_until=rate_limited_until,
            rate_limit_reason=rate_limit_reason,
        )

    async def get_all_health(self) -> list[AccountHealth]:
        backends = await self._accounts.list()
        result = []
        for b in backends:
            if b.status == BackendStatus.READY:
                result.append(await self.get_health(b.id))
        return result

    async def mark_rate_limited(self, backend_id: str, cooldown_seconds: int, reason: str) -> None:
        until = datetime.now(UTC) + timedelta(seconds=cooldown_seconds)
        usage_repo = await self._storage.usage()
        await usage_repo.set_rate_limited(backend_id, until, reason)
        logger.info(
            "marked %s rate-limited for %ds: %s",
            backend_id,
            cooldown_seconds,
            reason,
        )

    async def mark_used(self, backend_id: str) -> None:
        usage_repo = await self._storage.usage()
        await usage_repo.set_last_used(backend_id, datetime.now(UTC))

    # ── Polling ──

    async def poll_all(self) -> None:
        backends = await self._accounts.list()
        usage_repo = await self._storage.usage()
        for b in backends:
            if b.status != BackendStatus.READY:
                continue

            # Infrastructure: credential resolution (vault/storage errors are serious)
            try:
                impl = self._accounts._impl_for(b.kind)
                repo = await self._storage.backends()
                stored = await repo.get_credential(b.id)
                if stored is None:
                    logger.info("poll: skipping %s — no stored credential", b.id)
                    continue
                plaintext = await self._accounts._vault.decrypt(
                    stored.ciphertext, context={"backend_id": b.id}
                )
                isolation_dir = self._accounts._isolation_dir(b.id)
            except Exception:
                logger.error(
                    "poll: infrastructure failure for %s",
                    b.id,
                    exc_info=True,
                )
                continue

            # External API call (network errors are expected/transient)
            try:
                windows = await impl.get_usage(plaintext, isolation_dir=isolation_dir)
                if windows:
                    await usage_repo.put_snapshot(b.id, windows)
                await usage_repo.set_last_polled(b.id, datetime.now(UTC))
            except Exception:
                logger.warning(
                    "poll: usage fetch failed for %s (kind=%s)",
                    b.id,
                    b.kind,
                    exc_info=True,
                )
