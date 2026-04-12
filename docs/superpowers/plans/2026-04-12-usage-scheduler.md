# Usage Tracking + Account Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rate limit tracking and automatic account scheduling so consumers call `scheduler.pick()` and get the best available account without caring about rate limits.

**Architecture:** `UsageWindow` domain type + `get_usage()` on BackendProtocol + `AccountScheduler` service with `pick()` algorithm that reads cached health from SQLite. Background poller refreshes usage every 60s. Priority chain stored in `fallback_chains` table.

**Tech Stack:** Python (msgspec, aiosqlite, httpx, litestar), TypeScript

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `packages/core/src/ai_accounts_core/domain/usage.py` | UsageWindow, AccountHealth, FallbackChainEntry, PickResult |
| Modify | `packages/core/src/ai_accounts_core/protocols/backend.py` | Add get_usage() to BackendProtocol |
| Modify | `packages/core/src/ai_accounts_core/protocols/storage.py` | Add UsageRepository protocol |
| Modify | `packages/core/src/ai_accounts_core/adapters/storage_sqlite/schema.sql` | usage_snapshots + fallback_chains tables, new columns on backends |
| Modify | `packages/core/src/ai_accounts_core/adapters/storage_sqlite/storage.py` | SqliteUsageRepo implementation |
| Create | `packages/core/src/ai_accounts_core/services/scheduler.py` | AccountScheduler — pick, chain CRUD, health, mark_rate_limited, poll_all |
| Modify | `packages/core/src/ai_accounts_core/backends/claude.py` | get_usage() via Anthropic OAuth API |
| Modify | `packages/core/src/ai_accounts_core/backends/codex.py` | get_usage() via OpenAI API |
| Modify | `packages/core/src/ai_accounts_core/backends/gemini.py` | get_usage() via Google API |
| Modify | `packages/core/src/ai_accounts_core/backends/opencode.py` | get_usage() returns [] |
| Modify | `packages/core/src/ai_accounts_core/testing/fakes.py` | FakeBackend.get_usage() + FakeUsageRepo |
| Create | `packages/litestar/src/ai_accounts_litestar/routes/scheduler.py` | Scheduler REST routes |
| Modify | `packages/litestar/src/ai_accounts_litestar/app.py` | Wire scheduler + poller |
| Create | `packages/ts-core/src/types/scheduler.ts` | TS types |
| Modify | `packages/ts-core/src/client/index.ts` | Client methods |

---

## Task 1: Domain Types

**Files:**
- Create: `packages/core/src/ai_accounts_core/domain/usage.py`
- Test: `packages/core/tests/domain/test_usage_types.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/domain/test_usage_types.py
import msgspec
from datetime import datetime, UTC
from ai_accounts_core.domain.usage import UsageWindow, AccountHealth, FallbackChainEntry, PickResult

def test_usage_window_roundtrip():
    w = UsageWindow(window_type="five_hour", usage_percent=42.5, resets_at=datetime(2026, 4, 12, tzinfo=UTC))
    raw = msgspec.json.encode(w)
    decoded = msgspec.json.decode(raw, type=UsageWindow)
    assert decoded.usage_percent == 42.5
    assert decoded.window_type == "five_hour"

def test_account_health_roundtrip():
    h = AccountHealth(
        backend_id="bkd-1", kind="claude",
        windows=(UsageWindow(window_type="five_hour", usage_percent=10.0, resets_at=None),),
    )
    raw = msgspec.json.encode(h)
    decoded = msgspec.json.decode(raw, type=AccountHealth)
    assert decoded.kind == "claude"
    assert len(decoded.windows) == 1

def test_fallback_chain_entry():
    e = FallbackChainEntry(backend_id="bkd-1", priority=0)
    assert e.priority == 0

def test_pick_result():
    r = PickResult(backend_id="bkd-1", kind="claude", credential=b"sk-test", isolation_dir="/tmp/x")
    assert r.credential == b"sk-test"
    assert r.retry_after is None
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest packages/core/tests/domain/test_usage_types.py -v
```

- [ ] **Step 3: Implement domain types**

```python
# packages/core/src/ai_accounts_core/domain/usage.py
from datetime import datetime
import msgspec

class UsageWindow(msgspec.Struct, frozen=True, kw_only=True):
    window_type: str
    usage_percent: float
    resets_at: datetime | None
    tokens_used: int | None = None
    tokens_limit: int | None = None

class AccountHealth(msgspec.Struct, frozen=True, kw_only=True):
    backend_id: str
    kind: str
    windows: tuple[UsageWindow, ...]
    rate_limited_until: datetime | None = None
    rate_limit_reason: str | None = None
    last_used_at: datetime | None = None
    last_polled_at: datetime | None = None

class FallbackChainEntry(msgspec.Struct, frozen=True, kw_only=True):
    backend_id: str
    priority: int

class PickResult(msgspec.Struct, frozen=True, kw_only=True):
    backend_id: str
    kind: str
    credential: bytes
    isolation_dir: str
    retry_after: datetime | None = None
```

- [ ] **Step 4: Run test — expect PASS**
- [ ] **Step 5: Commit** `feat(core): UsageWindow, AccountHealth, FallbackChainEntry, PickResult domain types`

---

## Task 2: Storage — UsageRepository Protocol + SQLite Implementation

**Files:**
- Modify: `packages/core/src/ai_accounts_core/protocols/storage.py`
- Modify: `packages/core/src/ai_accounts_core/adapters/storage_sqlite/schema.sql`
- Modify: `packages/core/src/ai_accounts_core/adapters/storage_sqlite/storage.py`
- Modify: `packages/core/src/ai_accounts_core/testing/fakes.py`
- Test: `packages/core/tests/storage/test_usage_repo.py`

- [ ] **Step 1: Add UsageRepository protocol**

Add to `protocols/storage.py`:

```python
from ai_accounts_core.domain.usage import UsageWindow, FallbackChainEntry

@runtime_checkable
class UsageRepository(Protocol):
    async def put_snapshot(self, backend_id: str, windows: list[UsageWindow]) -> None: ...
    async def get_latest_snapshots(self, backend_id: str) -> list[UsageWindow]: ...
    async def set_rate_limited(self, backend_id: str, until: datetime, reason: str) -> None: ...
    async def clear_rate_limited(self, backend_id: str) -> None: ...
    async def get_rate_limit_state(self, backend_id: str) -> tuple[datetime | None, str | None]: ...
    async def set_last_used(self, backend_id: str, at: datetime) -> None: ...
    async def set_last_polled(self, backend_id: str, at: datetime) -> None: ...
    async def set_chain(self, entries: list[FallbackChainEntry]) -> None: ...
    async def get_chain(self) -> list[FallbackChainEntry]: ...
```

Add `async def usage(self) -> UsageRepository: ...` to `StorageProtocol`.

- [ ] **Step 2: Add schema tables**

Append to `schema.sql`:

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
CREATE INDEX IF NOT EXISTS idx_usage_snapshots_backend ON usage_snapshots(backend_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS fallback_chains (
    backend_id TEXT NOT NULL REFERENCES backends(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL,
    PRIMARY KEY (backend_id)
);
```

- [ ] **Step 3: Implement _SqliteUsageRepo in storage.py**

Follow existing pattern (_SqliteBackendRepo, etc). Implement all UsageRepository methods using the new tables. For `set_rate_limited` / `get_rate_limit_state` / `set_last_used` / `set_last_polled`, use UPDATE on backends table (add columns via ALTER TABLE in migrate if needed or just include in schema).

- [ ] **Step 4: Add FakeUsageRepo to fakes.py**

In-memory dicts matching the protocol.

- [ ] **Step 5: Write test, run, fix, commit**

```bash
uv run pytest packages/core/tests/storage/test_usage_repo.py -v
```

Commit: `feat(core): UsageRepository protocol + SQLite implementation + schema`

---

## Task 3: BackendProtocol.get_usage() + Backend Implementations

**Files:**
- Modify: `packages/core/src/ai_accounts_core/protocols/backend.py`
- Modify: `packages/core/src/ai_accounts_core/backends/claude.py`
- Modify: `packages/core/src/ai_accounts_core/backends/codex.py`
- Modify: `packages/core/src/ai_accounts_core/backends/gemini.py`
- Modify: `packages/core/src/ai_accounts_core/backends/opencode.py`
- Modify: `packages/core/src/ai_accounts_core/testing/fakes.py`
- Test: `packages/core/tests/backends/test_claude_usage.py`
- Test: `packages/core/tests/backends/test_codex_usage.py`
- Test: `packages/core/tests/backends/test_gemini_usage.py`

- [ ] **Step 1: Add get_usage() to BackendProtocol**

```python
async def get_usage(
    self, credential: bytes, *, isolation_dir: Path,
) -> list[UsageWindow]: ...
```

- [ ] **Step 2: Implement Claude get_usage()**

```python
async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list[UsageWindow]:
    api_key = credential.decode("utf-8").strip()
    if api_key.startswith("sk-ant-"):
        return []  # API keys can't access usage endpoint
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.anthropic.com/api/oauth/usage",
                headers={"Authorization": f"Bearer {api_key}", "anthropic-beta": "oauth-2025-04-20"},
                timeout=15.0,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            windows = []
            for w in data.get("windows", []):
                windows.append(UsageWindow(
                    window_type=w["window_type"],
                    usage_percent=w.get("utilization", 0.0),
                    resets_at=datetime.fromisoformat(w["resets_at"]) if w.get("resets_at") else None,
                ))
            return windows
    except Exception:
        return []
```

- [ ] **Step 3: Implement Codex, Gemini, OpenCode get_usage()**

Codex: `GET https://chatgpt.com/backend-api/wham/usage` with Bearer token. Parse `rate_limits[].primary_window.used_percent` and `reset_at`.

Gemini: `POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota` with Bearer token. Parse `buckets[].remainingFraction` → `(1 - frac) * 100`.

OpenCode: Return `[]` (OpenRouter has no usage API).

- [ ] **Step 4: FakeBackend.get_usage()**

```python
async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
    from ai_accounts_core.domain.usage import UsageWindow
    self.calls.append(("get_usage", credential))
    return [UsageWindow(window_type="five_hour", usage_percent=25.0, resets_at=None)]
```

- [ ] **Step 5: Write tests with httpx_mock, run, commit**

Commit: `feat(core): get_usage() for all backends — Claude, Codex, Gemini usage APIs`

---

## Task 4: AccountScheduler Service

**Files:**
- Create: `packages/core/src/ai_accounts_core/services/scheduler.py`
- Test: `packages/core/tests/services/test_scheduler.py`

- [ ] **Step 1: Write tests for pick(), chain CRUD, mark_rate_limited**

```python
# packages/core/tests/services/test_scheduler.py
import pytest
from datetime import datetime, UTC, timedelta
from ai_accounts_core.services.scheduler import AccountScheduler
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.domain.usage import FallbackChainEntry
from ai_accounts_core.testing.fakes import FakeStorage, FakeVault, FakeBackend

@pytest.fixture
async def scheduler(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(storage=storage, vault=vault, backends={"fake": fake}, isolation_base_dir=tmp_path)
    b1 = await accounts.create(kind="fake", display_name="Account 1")
    await accounts.store_credential(b1.id, b"sk-fake-1")
    await accounts.validate(b1.id)
    b2 = await accounts.create(kind="fake", display_name="Account 2")
    await accounts.store_credential(b2.id, b"sk-fake-2")
    await accounts.validate(b2.id)
    sched = AccountScheduler(account_service=accounts, storage=storage)
    return sched, b1.id, b2.id

@pytest.mark.asyncio
async def test_pick_returns_highest_priority(scheduler):
    sched, b1, b2 = scheduler
    await sched.set_chain([FallbackChainEntry(backend_id=b1, priority=0), FallbackChainEntry(backend_id=b2, priority=1)])
    result = await sched.pick()
    assert result is not None
    assert result.backend_id == b1

@pytest.mark.asyncio
async def test_pick_skips_rate_limited(scheduler):
    sched, b1, b2 = scheduler
    await sched.set_chain([FallbackChainEntry(backend_id=b1, priority=0), FallbackChainEntry(backend_id=b2, priority=1)])
    await sched.mark_rate_limited(b1, 3600, "429 from API")
    result = await sched.pick()
    assert result is not None
    assert result.backend_id == b2

@pytest.mark.asyncio
async def test_pick_returns_none_when_all_exhausted(scheduler):
    sched, b1, b2 = scheduler
    await sched.set_chain([FallbackChainEntry(backend_id=b1, priority=0), FallbackChainEntry(backend_id=b2, priority=1)])
    await sched.mark_rate_limited(b1, 3600, "429")
    await sched.mark_rate_limited(b2, 1800, "429")
    result = await sched.pick()
    assert result is None

@pytest.mark.asyncio
async def test_pick_filters_by_kind(scheduler):
    sched, b1, b2 = scheduler
    await sched.set_chain([FallbackChainEntry(backend_id=b1, priority=0), FallbackChainEntry(backend_id=b2, priority=1)])
    result = await sched.pick(kind="fake")
    assert result is not None

@pytest.mark.asyncio
async def test_chain_crud(scheduler):
    sched, b1, b2 = scheduler
    await sched.set_chain([FallbackChainEntry(backend_id=b2, priority=0), FallbackChainEntry(backend_id=b1, priority=1)])
    chain = await sched.get_chain()
    assert chain[0].backend_id == b2
    assert chain[1].backend_id == b1

@pytest.mark.asyncio
async def test_poll_all_updates_health(scheduler):
    sched, b1, b2 = scheduler
    await sched.poll_all()
    health = await sched.get_health(b1)
    assert health.last_polled_at is not None
    assert len(health.windows) >= 1

@pytest.mark.asyncio
async def test_get_all_health(scheduler):
    sched, b1, b2 = scheduler
    await sched.poll_all()
    all_health = await sched.get_all_health()
    assert len(all_health) == 2
```

- [ ] **Step 2: Implement AccountScheduler**

Core `pick()` algorithm:
1. Load chain (ordered by priority)
2. Filter by kind if specified
3. If chain empty, use all READY backends
4. For each candidate: skip if rate_limited_until > now, skip if any window >= 95%
5. Return lowest max_usage_percent candidate
6. If all exhausted: return None

- [ ] **Step 3: Run tests, fix, commit**

Commit: `feat(core): AccountScheduler — pick, chain CRUD, health, poll_all`

---

## Task 5: Litestar Scheduler Routes + App Wiring

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/scheduler.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Test: `packages/litestar/tests/test_scheduler_routes.py`

- [ ] **Step 1: Create SchedulerController**

```
GET  /api/v1/scheduler/health              → all account health
GET  /api/v1/scheduler/health/{backend_id} → single account health
POST /api/v1/scheduler/pick                → pick best account (body: {kind?})
GET  /api/v1/scheduler/chain               → get priority chain
PUT  /api/v1/scheduler/chain               → set priority chain
POST /api/v1/scheduler/mark-limited        → mark account rate-limited
```

- [ ] **Step 2: Wire into app.py**

Add `AccountScheduler` to DI. Add background poller task (same pattern as login sweep).

- [ ] **Step 3: Write route tests, run, commit**

Commit: `feat(litestar): scheduler routes + background usage poller`

---

## Task 6: TypeScript Types + Client Methods

**Files:**
- Create: `packages/ts-core/src/types/scheduler.ts`
- Modify: `packages/ts-core/src/client/index.ts`
- Modify: `packages/ts-core/src/index.ts`
- Test: `packages/ts-core/tests/scheduler.test.ts`

- [ ] **Step 1: Create TS types**

```typescript
// packages/ts-core/src/types/scheduler.ts
export interface UsageWindowDTO { window_type: string; usage_percent: number; resets_at: string | null; }
export interface AccountHealthDTO { backend_id: string; kind: string; windows: UsageWindowDTO[]; rate_limited_until: string | null; last_polled_at: string | null; }
export interface PickResultDTO { backend_id: string; kind: string; retry_after: string | null; }
export interface FallbackChainEntryDTO { backend_id: string; priority: number; }
```

- [ ] **Step 2: Add client methods**

```typescript
getSchedulerHealth(): Promise<{ items: AccountHealthDTO[] }>
getAccountHealth(id: string): Promise<AccountHealthDTO>
schedulerPick(kind?: string): Promise<PickResultDTO | null>
getChain(): Promise<{ entries: FallbackChainEntryDTO[] }>
setChain(entries: FallbackChainEntryDTO[]): Promise<void>
markRateLimited(backendId: string, seconds: number, reason: string): Promise<void>
```

- [ ] **Step 3: Build, test, commit**

Commit: `feat(ts-core): scheduler types and client methods`

---

## Task 7: Version Bump + Release

- [ ] **Step 1: Update CHANGELOG.md**
- [ ] **Step 2: Bump versions to 0.4.0a1**
- [ ] **Step 3: Rebuild frontend packages**
- [ ] **Step 4: Run full test suite**
- [ ] **Step 5: Commit** `release: 0.4.0-alpha.1 (usage tracking + account scheduler)`
