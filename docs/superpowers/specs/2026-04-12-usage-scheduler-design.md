# Usage Tracking + Account Scheduler Design Spec

**Date:** 2026-04-12
**Status:** Approved
**Goal:** Add rate limit tracking and automatic account scheduling to ai-accounts so consumers call `scheduler.pick()` and get the best available account without caring about rate limits.

---

## Overview

Three new components in `ai-accounts-core`:

1. **UsageProvider** — per-backend method that fetches rate limit windows from provider APIs
2. **AccountHealthStore** — persists usage snapshots + rate-limit state per account in SQLite
3. **AccountScheduler** — `pick(kind?)` returns the best available account using priority chain + health data

Plus a **background poller** (60s interval) and **reactive 429 detection** from chat() errors.

## Architecture

```
Consumer calls scheduler.pick("claude")
    → Scheduler reads priority chain from DB
    → For each chain entry (by priority), checks cached health
    → Returns first healthy account (or least-utilized if all near limit)
    → If all exhausted: returns None + earliest reset time

Background poller (every 60s):
    → For each logged-in account with READY status, calls get_usage()
    → Stores UsageSnapshot in SQLite
    → Marks accounts rate_limited if any window >= 95%

Reactive 429 detection:
    → If chat() gets a 429, caller marks account via scheduler.mark_rate_limited()
    → Scheduler excludes it on next pick()
```

---

## Domain Types

### `domain/usage.py`

```python
class UsageWindow(msgspec.Struct, frozen=True, kw_only=True):
    """A single rate limit window from a provider."""
    window_type: str          # "five_hour", "seven_day", "primary", "per_model"
    usage_percent: float      # 0.0 - 100.0
    resets_at: datetime | None
    tokens_used: int | None = None
    tokens_limit: int | None = None

class AccountHealth(msgspec.Struct, frozen=True, kw_only=True):
    """Cached health snapshot for a single account."""
    backend_id: str
    kind: str                 # "claude", "codex", "gemini", "opencode"
    windows: tuple[UsageWindow, ...]
    rate_limited_until: datetime | None = None
    rate_limit_reason: str | None = None
    last_used_at: datetime | None = None
    last_polled_at: datetime | None = None

class FallbackChainEntry(msgspec.Struct, frozen=True, kw_only=True):
    """One entry in the user-configured priority chain."""
    backend_id: str           # specific account ID (e.g., "bkd-abc123")
    priority: int             # 0 = highest priority

class PickResult(msgspec.Struct, frozen=True, kw_only=True):
    """Result from scheduler.pick() — the chosen account."""
    backend_id: str
    kind: str                 # "claude", "codex", "gemini", "opencode"
    credential: bytes         # decrypted credential, ready to use
    isolation_dir: str        # path to backend's isolation directory
    retry_after: datetime | None = None  # set only when returning None (all exhausted)
```

---

## Protocol Extension

### `protocols/backend.py` — new method

```python
@runtime_checkable
class BackendProtocol(Protocol):
    # ... existing methods ...

    async def get_usage(
        self, credential: bytes, *, isolation_dir: Path
    ) -> list[UsageWindow]:
        """Fetch current rate limit windows from the provider API.

        Returns empty list if the provider doesn't support usage queries
        or the credential type doesn't allow it (e.g., API keys may not
        have access to usage endpoints).
        """
        ...
```

---

## Backend Implementations

### Claude — `backends/claude.py`

```
GET https://api.anthropic.com/api/oauth/usage
Headers: Authorization: Bearer {oauth_token}
         anthropic-beta: oauth-2025-04-20

Response: { windows: [{ window_type, utilization, resets_at }] }
```

Credential resolution: The stored credential may be an API key (`sk-ant-...`) or an OAuth token. Only OAuth tokens can access the usage endpoint. API key accounts return empty `[]`.

Windows returned: `five_hour`, `seven_day`, `seven_day_sonnet`

### Codex (OpenAI) — `backends/codex.py`

```
GET https://chatgpt.com/backend-api/wham/usage
Headers: Authorization: Bearer {oauth_token}
         ChatGPT-Account-Id: {account_id}  (optional)

Response: { rate_limits: [{ ... primary_window, secondary_window }], additional_rate_limits: [...] }
```

Windows returned: `primary_window`, `secondary_window` per rate_limit entry. Each has `used_percent` and `reset_at` (Unix timestamp).

### Gemini — `backends/gemini.py`

```
POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota
Body: {"project": "cloud-code-assist"}
Headers: Authorization: Bearer {oauth_token}

Response: { buckets: [{ modelId, remainingFraction, resetTime }] }
```

Windows returned: one per model bucket. `usage_percent = (1 - remainingFraction) * 100`.

### OpenCode — `backends/opencode.py`

OpenCode uses OpenRouter which doesn't expose a rate limit API. Returns empty `[]`. Account health is tracked reactively via 429 detection only.

---

## AccountScheduler Service

### `services/scheduler.py`

```python
class AccountScheduler:
    def __init__(
        self,
        *,
        account_service: AccountService,
        storage: StorageProtocol,
        poll_interval_seconds: float = 60.0,
    ) -> None: ...

    # ── Scheduling ──

    async def pick(self, kind: str | None = None) -> PickResult | None:
        """Pick the best available account.

        If kind is specified, only considers accounts of that backend kind.
        If kind is None, walks the full priority chain across all providers.

        Returns None if all accounts are rate-limited. The PickResult
        includes retry_after (earliest reset time across all candidates)
        so the consumer knows when to try again.
        """

    # ── Priority Chain ──

    async def set_chain(self, entries: list[FallbackChainEntry]) -> None:
        """Replace the entire priority chain. Transactional."""

    async def get_chain(self) -> list[FallbackChainEntry]:
        """Get the current priority chain, ordered by priority."""

    # ── Health ──

    async def get_health(self, backend_id: str) -> AccountHealth:
        """Get cached health for a single account."""

    async def get_all_health(self) -> list[AccountHealth]:
        """Get cached health for all accounts."""

    async def mark_rate_limited(
        self, backend_id: str, cooldown_seconds: int, reason: str
    ) -> None:
        """Reactively mark an account as rate-limited (e.g., after a 429).
        Sets rate_limited_until = now + cooldown_seconds."""

    async def mark_used(self, backend_id: str) -> None:
        """Update last_used_at timestamp for an account."""

    # ── Polling ──

    async def poll_all(self) -> None:
        """Fetch usage for all READY accounts and update snapshots.
        Called by the background poller task."""
```

### Pick Algorithm

```
pick(kind=None):
    1. Load priority chain from DB (ordered by priority ASC)
    2. If kind specified, filter chain to entries matching that kind
    3. If chain is empty, fall back to all READY accounts ordered by kind
    4. For each candidate:
        a. Load cached AccountHealth
        b. Skip if rate_limited_until > now
        c. Skip if any window usage_percent >= 95%
        d. Score: lower max_usage_percent = better
    5. Return candidate with lowest max_usage_percent
    6. If all candidates exhausted:
        a. Find earliest reset time across all candidates
        b. Return None with retry_after set
```

---

## Storage Schema

### New tables in `schema.sql`

```sql
CREATE TABLE IF NOT EXISTS usage_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backend_id TEXT NOT NULL REFERENCES backends(id) ON DELETE CASCADE,
    window_type TEXT NOT NULL,
    usage_percent REAL NOT NULL,
    tokens_used INTEGER,
    tokens_limit INTEGER,
    resets_at TEXT,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_snapshots_backend
    ON usage_snapshots(backend_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS fallback_chains (
    backend_id TEXT NOT NULL REFERENCES backends(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL,
    PRIMARY KEY (backend_id)
);
```

### New columns on `backends` table

```sql
ALTER TABLE backends ADD COLUMN rate_limited_until TEXT;
ALTER TABLE backends ADD COLUMN rate_limit_reason TEXT;
ALTER TABLE backends ADD COLUMN last_used_at TEXT;
ALTER TABLE backends ADD COLUMN last_polled_at TEXT;
```

Handled via schema migration (increment `_CURRENT_VERSION`).

---

## Litestar Routes

### `routes/scheduler.py`

```
GET  /api/v1/scheduler/health              → { items: AccountHealth[] }
GET  /api/v1/scheduler/health/{backend_id} → AccountHealth
POST /api/v1/scheduler/pick                → PickResult | { retry_after }
     Body: { kind?: string }
GET  /api/v1/scheduler/chain               → { entries: FallbackChainEntry[] }
PUT  /api/v1/scheduler/chain               → { entries: FallbackChainEntry[] }
     Body: { entries: [{ backend_id, priority }] }
POST /api/v1/scheduler/mark-limited        → 204
     Body: { backend_id, cooldown_seconds, reason }
```

---

## TypeScript Client

### `types/scheduler.ts`

```typescript
interface UsageWindowDTO { window_type: string; usage_percent: number; resets_at: string | null; }
interface AccountHealthDTO { backend_id: string; kind: string; windows: UsageWindowDTO[]; rate_limited_until: string | null; last_polled_at: string | null; }
interface PickResultDTO { backend_id: string; kind: string; retry_after: string | null; }
interface FallbackChainEntryDTO { backend_id: string; priority: number; }
```

### Client methods on `AiAccountsClient`

```typescript
getSchedulerHealth(): Promise<{ items: AccountHealthDTO[] }>
getAccountHealth(id: string): Promise<AccountHealthDTO>
schedulerPick(kind?: string): Promise<PickResultDTO | null>
getChain(): Promise<{ entries: FallbackChainEntryDTO[] }>
setChain(entries: FallbackChainEntryDTO[]): Promise<void>
markRateLimited(backendId: string, seconds: number, reason: string): Promise<void>
```

---

## Background Poller

Integrated into `create_app()` as an asyncio task (same pattern as the login session sweep):

```python
async def _usage_poll_loop(scheduler: AccountScheduler) -> None:
    while True:
        await asyncio.sleep(scheduler.poll_interval_seconds)
        try:
            await scheduler.poll_all()
        except Exception:
            logger.exception("usage poll failed")
```

---

## Testing Strategy

### FakeBackend.get_usage()

Returns canned usage windows for testing:

```python
async def get_usage(self, credential, *, isolation_dir):
    return [UsageWindow(window_type="five_hour", usage_percent=25.0, resets_at=None)]
```

### Key test scenarios

1. `pick()` returns highest-priority healthy account
2. `pick()` skips rate-limited accounts
3. `pick()` returns None with retry_after when all exhausted
4. `pick(kind="claude")` filters to Claude accounts only
5. `mark_rate_limited()` makes account unavailable to pick()
6. `poll_all()` updates cached health snapshots
7. `set_chain()` / `get_chain()` CRUD
8. Schema migration adds new columns without losing data

---

## What's NOT in scope

- **Mid-execution rotation** — consumer responsibility (too coupled to execution model)
- **Circuit breakers** — consumer adds on top of pick()
- **Budget tracking** — separate concern, not rate-limit related
- **Retry persistence** — consumer decides retry policy
- **Historical analytics** — snapshots are stored, but aggregation queries are consumer-side
- **Vue UI for scheduler** — API-only; consumers build their own UI

The package gives consumers `pick()` and health data. Consumers decide what to do when all accounts are exhausted.
