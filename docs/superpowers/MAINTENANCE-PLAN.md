# ai-accounts Maintenance Implementation Plan

> Based on the 6-agent audit completed 2026-04-11. Covers both repos:
> `~/Developer/Projects/ai-accounts` (branch `feat/0.3.0-alpha.1`) and
> `~/Developer/Projects/Agented` (branch `main`).

**Goal:** Fix all Critical + High findings before `0.3.0` stable. Ship as `0.3.0-alpha.3` (alongside PTY work) or as a dedicated `0.3.0-alpha.2.post1` hotfix if PTY timeline slips.

---

## Phase 1 — Security (blocks release)

*Estimated: 1 day. All items are release blockers.*

### 1.1 SSRF in `forward_cliproxy_callback` [C-4]

**Repo:** ai-accounts
**File:** `packages/core/src/ai_accounts_core/cliproxy/manager.py`

**Problem:** `callback_url` from POST body is parsed and forwarded to `http://127.0.0.1:{any_port}{any_path}` — attacker can hit any localhost service.

**Fix:**
- Add `CLIPROXY_ALLOWED_PORTS = {54545, 8085}` constant (the two known cliproxy callback ports)
- Add `CLIPROXY_ALLOWED_PATH_PREFIX = "/callback"` constant
- Validate `parsed.port in CLIPROXY_ALLOWED_PORTS` before forwarding
- Validate `parsed.path.startswith(CLIPROXY_ALLOWED_PATH_PREFIX)`
- Reject with `{"status": "error", "message": "invalid callback URL"}` if either check fails
- Also validate `parsed.scheme in ("http", "https")` and `parsed.hostname in ("localhost", "127.0.0.1")`

**Test:** Add `test_forward_callback_rejects_disallowed_port` and `test_forward_callback_rejects_path_traversal`.

### 1.2 Gemini plaintext token writes + path traversal [C-5, M-3]

**Repo:** ai-accounts
**File:** `packages/core/src/ai_accounts_core/backends/gemini.py` (`_GeminiDirectOAuthSession._write_credentials`)

**Problem:** OAuth tokens written as plaintext JSON to user-controlled `config_path`; file mode 0o644; no vault involvement; path traversal possible via PATCH.

**Fix:**
- Write credential files with `os.chmod(path, 0o600)` after write
- Validate `config_path` is either None/empty (use default `~/.gemini`) or resolves to a path under `self._isolation_dir` — reject anything with `..` components
- Store the raw token bundle via vault (call `vault.encrypt(json_bytes, context={"backend_id": ..., "kind": "gemini"})`) and persist via `AccountService.store_credential()` — the Gemini CLI can read `~/.gemini/oauth_creds.json` independently, but the vault copy is the authoritative one for ai-accounts
- The `~/.cli-proxy-api/gemini-<email>.json` write is acceptable (CLIProxyAPI needs it there) but enforce `0o600` and validate the email doesn't contain path separators

**Test:** Add `test_direct_oauth_rejects_path_traversal_config` and `test_credential_file_permissions`.

### 1.3 Wire `ApiKeyAuth` in Agented sidecar [M-2]

**Repo:** Agented
**File:** `backend/scripts/run_ai_accounts.py`

**Problem:** `auth=NoAuth()` makes all sidecar endpoints unauthenticated. Anyone on the same machine can create/delete accounts, trigger login flows, install CLIs.

**Fix:**
- Import `ApiKeyAuth` from `ai_accounts_core.adapters.auth_apikey`
- Read `AI_ACCOUNTS_API_KEY` from env (or fall back to the same key Flask uses via `agented.db` settings table)
- For development, support `NoAuth` via explicit `AI_ACCOUNTS_AUTH=none` env var override
- Wire the `AiAccountsClient` in `frontend/src/main.ts` with `token` matching the API key

**Files touched:**
- `backend/scripts/run_ai_accounts.py` — swap `NoAuth()` for `ApiKeyAuth.from_env()`
- `frontend/src/main.ts` — pass `token` to `AiAccountsClient` constructor from `getApiKey()` in `services/api/client.ts`

### 1.4 Internal error message leak [SF-H7]

**Repo:** ai-accounts
**File:** `packages/litestar/src/ai_accounts_litestar/errors.py`

**Problem:** Fallback error handler returns `str(exc)` to client — may leak file paths, credential fragments.

**Fix:** Replace fallback with generic message; log actual error server-side:
```python
logger.exception("Unhandled service error")
return Response(
    content={"error": {"code": "internal_error", "message": "An internal error occurred"}},
    status_code=500,
)
```

---

## Phase 2 — Reliability (blocks release)

*Estimated: 2 days. Race conditions and resource leaks that cause real user-facing bugs.*

### 2.1 LoginSession cancel/events race — double `os.waitpid` [C-1]

**Repo:** ai-accounts
**Files:** All backend files in `packages/core/src/ai_accounts_core/backends/{claude,codex,gemini,opencode}.py`

**Problem:** `cancel()` calls `terminate()` without `wait()`; concurrent `events()` also calls `wait()` → two `waitpid` on same PID.

**Fix for all cli_browser/oauth_device sessions:**
- Add an `asyncio.Lock` (`self._cleanup_lock`) to each session class
- In `cancel()`: acquire lock, call `terminate()` + `wait()`, set `done=True`, release lock
- In `events()` finally block: acquire lock, call `terminate()` + `wait()` only if not already done, release lock
- Set `self._pid = None` after successful `wait()` in `CliOrchestrator` to make it idempotent

### 2.2 Thread pool leak in CliOrchestrator [C-2]

**Repo:** ai-accounts
**File:** `packages/core/src/ai_accounts_core/login/cli_orchestrator.py`

**Problem:** If `wait()` is never called, `_reader_task`'s thread blocks on `os.read()` forever; `master_fd` never closed.

**Fix:**
- In `terminate()`: close `master_fd` immediately (causes `_read_once` to return empty → reader loop exits)
- In `wait()`: cancel `_reader_task` with a timeout before awaiting it
- Add `__del__` safeguard that closes `master_fd` if still open (with a `logger.warning`)
- Add `_reader_task.add_done_callback` that logs unexpected exceptions

### 2.3 SSE disconnect leaves subprocess running [C-3]

**Repo:** ai-accounts
**File:** `packages/litestar/src/ai_accounts_litestar/routes/login.py`

**Problem:** `gen()` finally block calls `registry.remove()` but not `session.cancel()`.

**Fix:**
```python
async def gen():
    try:
        async for event in session.events():
            yield {"event": "login", "data": msgspec.json.encode(event).decode()}
    finally:
        await session.cancel()
        await service.login_registry.remove(session_id)
```

### 2.4 `answers.get()` blocks forever; `cancel()` doesn't unblock [H-1]

**Repo:** ai-accounts
**Files:** All API-key + direct-OAuth session classes across all 4 backends

**Problem:** `await self._answers.get()` has no timeout; `cancel()` sets `_done=True` but doesn't wake the blocked coroutine.

**Fix (apply to every session that awaits `self._answers.get()`):**
```python
async def events(self) -> AsyncIterator[LoginEvent]:
    yield TextPrompt(...)
    try:
        ans = await asyncio.wait_for(self._answers.get(), timeout=300)
    except asyncio.TimeoutError:
        self._done = True
        yield LoginFailed(code="response_timeout", message="No response received within 5 minutes")
        return
    # ... process answer ...

async def cancel(self) -> None:
    self._done = True
    # Unblock any waiter
    with contextlib.suppress(asyncio.QueueFull):
        self._answers.put_nowait(PromptAnswer(prompt_id="__cancel__", answer=""))
```

Also change queue init to `asyncio.Queue(maxsize=1)` to prevent unbounded growth from repeated `respond()` calls.

### 2.5 `respond()` after done leaks sensitive data [H-2]

**Repo:** ai-accounts
**Files:** Same as 2.4

**Fix:** Guard in `respond()`:
```python
async def respond(self, answer: PromptAnswer) -> None:
    if self._done:
        return  # session already completed; discard
    await self._answers.put(answer)
```

### 2.6 `wait()` without `terminate()` hangs event loop [H-3]

**Repo:** ai-accounts
**Files:** `gemini.py`, `opencode.py`, `codex.py` — all `_*OAuthDeviceSession.events()` and `_*CliBrowserSession.events()`

**Problem:** After breaking from `read_output()` loop, `await self._orchestrator.wait()` called without first terminating the process → hangs if process is still running.

**Fix:** Insert `await self._orchestrator.terminate()` before `await self._orchestrator.wait()` in every backend's `events()` exit path. Also wrap `wait()` with a timeout:
```python
try:
    exit_code = await asyncio.wait_for(self._orchestrator.wait(), timeout=10)
except asyncio.TimeoutError:
    await self._orchestrator.kill()
    exit_code = await self._orchestrator.wait()
```

### 2.7 `useLoginSession.start()` no try/catch → permanent spinner [SF-C2]

**Repo:** ai-accounts
**File:** `packages/vue-headless/src/composables/useLoginSession.ts`

**Fix:**
```ts
async function start(id, flow, inputs) {
  // ... reset state ...
  status.value = 'running';
  try {
    const { session_id } = await client.beginLogin(id, flow, inputs);
    sessionId.value = session_id;
    emit({ type: 'login.started', ... });
    for await (const event of client.streamLogin(id, session_id)) {
      dispatch(event);
      if (status.value !== 'running') return;
    }
  } catch (err) {
    status.value = 'failed';
    errorCode.value = 'network_error';
    errorMessage.value = err instanceof Error ? err.message : String(err);
    emit({ type: 'login.failed', sessionId: sessionId.value ?? '', code: 'network_error', message: errorMessage.value });
  }
}
```

### 2.8 SSE JSON.parse failures silently dropped [SF-C1]

**Repo:** ai-accounts
**File:** `packages/ts-core/src/client/login-stream.ts`

**Fix:**
```ts
try {
  yield JSON.parse(payload) as LoginEvent;
} catch {
  console.warn('[ai-accounts] malformed SSE frame:', payload.slice(0, 200));
  consecutiveParseErrors++;
  if (consecutiveParseErrors >= 3) {
    yield { type: 'failed', code: 'stream_corrupt', message: 'Multiple malformed SSE frames received' } as LoginFailed;
    return;
  }
}
```

### 2.9 LoginSessionRegistry has no `close()` → orphan subprocesses on shutdown [SF-C3]

**Repo:** ai-accounts
**Files:** `packages/core/src/ai_accounts_core/login/registry.py` + `packages/litestar/src/ai_accounts_litestar/app.py`

**Fix:**
```python
# registry.py
async def close(self) -> None:
    """Cancel all active sessions and await pending cancel tasks."""
    async with self._lock:
        for entry in self._entries.values():
            if not entry.session.done:
                asyncio.create_task(entry.session.cancel())
        self._entries.clear()
    if self._pending_cancels:
        await asyncio.gather(*self._pending_cancels, return_exceptions=True)
    self._pending_cancels.clear()

# app.py — register as Litestar on_shutdown hook
app = Litestar(
    ...,
    on_shutdown=[lambda app: registry.close()],
)
```

---

## Phase 3 — Robustness

*Estimated: 1 day. Resource leaks and process management.*

### 3.1 Cliproxy temp dir leak [H-4]

**File:** `packages/core/src/ai_accounts_core/cliproxy/manager.py`

**Fix:** Use `tempfile.TemporaryDirectory` as a context manager:
```python
async def start_cliproxy_login(...):
    with tempfile.TemporaryDirectory(prefix="aia-cliproxy-") as fake_dir_str:
        fake_dir = Path(fake_dir_str)
        _setup_fake_open(fake_dir)  # extract the open-script creation
        # ... rest of the function ...
        # fake_dir auto-cleaned on exit
```
For the case where `proc` is returned alive (caller manages lifecycle), defer cleanup via the reaper task.

### 3.2 PTY child orphan on parent crash [H-5]

**File:** `packages/core/src/ai_accounts_core/login/cli_orchestrator.py`

**Fix:** In the `pid == 0` (child) branch, before `os.execvpe`:
```python
if pid == 0:
    # Set parent-death signal on Linux so the child doesn't outlive the parent
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except (OSError, AttributeError):
        pass  # macOS doesn't support prctl; document the limitation
    # ... existing chdir + execvpe ...
```

### 3.3 Cliproxy reaper task fire-and-forget [SF-C4, L-2]

**File:** `packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py`

**Fix:**
- Store the reaper task reference: `_ACTIVE_TASKS[proc_id] = asyncio.create_task(_reap())`
- Use `uuid.uuid4().hex` as key instead of `id(proc)`
- Add exception handling in `_reap()`:
```python
async def _reap():
    try:
        await asyncio.wait_for(proc.wait(), timeout=300)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
    except Exception:
        logger.warning("cliproxy reaper failed", exc_info=True)
    finally:
        _ACTIVE_PROCS.pop(proc_id, None)
        _ACTIVE_TASKS.pop(proc_id, None)
```

### 3.4 Triple-silent-catch in finally blocks [SF-H5]

**Files:** All backend `events()` finally blocks + `cancel()` methods

**Fix:** Replace bare `except Exception: pass` with:
```python
except (OSError, ProcessLookupError) as exc:
    logger.debug("cleanup: %s", exc)
```
**Critical:** Never catch `asyncio.CancelledError` — it breaks task cancellation semantics.

### 3.5 Cliproxy login/begin returns 201 for errors [SF-H6]

**File:** `packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py`

**Fix:** Use appropriate HTTP status codes:
- `status: "error"` → return HTTP 400 (or 404 if "not found")
- `status: "skipped"` → return HTTP 409 (Conflict) or HTTP 200 (OK with advisory)
- `status: "started"` and `status: "imported"` → keep HTTP 201

### 3.6 `shutil.rmtree(ignore_errors=True)` swallows deletion failures [SF-H4]

**File:** `packages/core/src/ai_accounts_core/services/accounts.py`

**Fix:**
```python
if isolation_dir.exists():
    try:
        shutil.rmtree(isolation_dir)
    except OSError as exc:
        logger.warning("failed to delete isolation dir %s: %s", isolation_dir, exc)
```

---

## Phase 4 — Infrastructure

*Estimated: 1-2 days. Deploy, observability, version strings.*

### 4.1 `just deploy` doesn't start sidecar [M-5]

**Repo:** Agented
**File:** `justfile`

**Fix:** Add sidecar to the `deploy` recipe:
```just
deploy: kill ensure-backend build
    @echo "Starting ai-accounts sidecar on port 20001..."
    cd backend && uv run python scripts/run_ai_accounts.py &
    @while ! curl -sf http://127.0.0.1:20001/health >/dev/null 2>&1; do sleep 0.5; done; echo "Sidecar ready."
    @echo "Starting backend via Gunicorn on port 20000..."
    cd backend && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES uv run gunicorn -c gunicorn.conf.py &
    @while ! curl -sf http://127.0.0.1:20000/health/readiness >/dev/null 2>&1; do sleep 1; done; echo "Backend ready."
    cd frontend && npm run dev
```
Also update `kill` to include port 20001 (already done in the migration).

### 4.2 Fix `__version__` mismatch

**Repo:** ai-accounts
**Files:**
- `packages/core/src/ai_accounts_core/__init__.py` — change `__version__ = "0.2.2"` to `"0.3.0a2"`
- `packages/litestar/src/ai_accounts_litestar/__init__.py` — same
- `packages/vue-styled/src/index.ts` — `version = '0.2.0'` → `'0.3.0-alpha.2'`

### 4.3 SQLite WAL mode [L-1]

**File:** `packages/core/src/ai_accounts_core/adapters/storage_sqlite/storage.py`

**Fix:** In `_ensure_conn()` or `migrate()`:
```python
await self._conn.execute("PRAGMA journal_mode = WAL")
```

### 4.4 `useTourMachine` initPromise never reset on rejection [M-4]

**Repo:** Agented
**File:** `frontend/src/composables/useTourMachine.ts`

**Fix:**
```ts
initPromise = initActor().catch((err) => {
  console.error('[tour] init failed:', err);
  initPromise = null;  // allow retry on next useTourMachine() call
  throw err;
});
```

### 4.5 Structured logging for login lifecycle

**Repo:** ai-accounts
**Files:** `cli_orchestrator.py`, `interactive.py`, `registry.py`, all backend `events()` methods

**Add:**
- `logger.info("login session started: kind=%s flow=%s sid=%s", ...)` at session creation
- `logger.info("login session completed: sid=%s status=%s", ...)` at complete/failed
- `logger.warning("login session swept (TTL expired): sid=%s", ...)` at sweep
- `logger.debug("pty output: %d bytes", len(chunk))` in read_output (guard with level check)
- `logger.info("menu detected: %d options, sid=%s", ...)` in interactive loop

### 4.6 Periodic session sweep via Litestar startup task

**File:** `packages/litestar/src/ai_accounts_litestar/app.py`

**Add:**
```python
async def _sweep_loop(registry: LoginSessionRegistry) -> None:
    while True:
        await asyncio.sleep(60)
        try:
            purged = await registry.sweep()
            if purged:
                logger.info("swept %d expired login sessions", purged)
        except Exception:
            logger.exception("session sweep failed")

# In create_app:
async def on_startup(app: Litestar) -> None:
    # ... existing startup ...
    app.state.sweep_task = asyncio.create_task(_sweep_loop(registry))

async def on_shutdown(app: Litestar) -> None:
    app.state.sweep_task.cancel()
    await registry.close()
```

---

## Phase 5 — Test Coverage

*Estimated: 2-3 days. Fill gaps identified in audit.*

### 5.1 `login/interactive.py` direct tests

**File:** `packages/core/tests/login/test_interactive.py` (new)

**Test cases:**
- `test_interactive_login_sends_action_after_idle` — scripted output with 2s gap → verify `/login\r` written
- `test_interactive_login_detects_menu_and_yields_text_prompt` — scripted menu output → verify TextPrompt emitted with parsed options
- `test_interactive_login_navigates_menu_via_arrow_keys` — respond with "3" → verify 2x `\x1b[B` + `\r` written
- `test_interactive_login_emits_url_prompt_after_action` — scripted URL output after `/login` → verify UrlPrompt
- `test_interactive_login_force_completes_on_success_idle` — success marker + 2s idle → verify LoginComplete
- `test_interactive_login_handles_cli_not_found` — FileNotFoundError from start() → LoginFailed

### 5.2 `cliproxy/manager.py` unit tests

**File:** `packages/core/tests/cliproxy/test_manager_unit.py` (new)

**Test cases:**
- `test_is_cliproxy_installed_returns_bool` (already exists; expand)
- `test_make_fake_open_dir_creates_executable` — verify the fake `open` script exists and is +x
- `test_start_cliproxy_login_returns_error_when_not_installed` — mock `shutil.which` to return None
- `test_start_cliproxy_login_captures_url_from_fake_open` — mock subprocess, write to `captured.url`, verify `oauth_url` populated
- `test_start_cliproxy_login_timeout_kills_process` — mock subprocess that never outputs → verify proc.kill called

### 5.3 SSE stream integration test

**File:** `packages/litestar/tests/test_login_routes.py` (modify existing xfail)

**Strategy:** The current test is xfailed because Litestar's `AsyncTestClient` has concurrency timing issues with bidirectional SSE. Options:
1. Use `httpx.AsyncClient` with a running uvicorn test server instead of `AsyncTestClient`
2. Test the `gen()` coroutine directly (bypass HTTP layer; test the async generator output)
3. Keep as integration and use longer delays for timing

Recommend option 2: extract `gen()` into a testable function, test its output directly against a `FakeLoginSession`.

### 5.4 Fix pre-existing tour machine test failures (11)

**Repo:** Agented
**Files:** `frontend/src/machines/__tests__/tourMachine.test.ts`, `frontend/src/composables/__tests__/useTourMachine.test.ts`, `frontend/src/components/tour/__tests__/TourOverlay.test.ts`, `frontend/src/components/tour/__tests__/TourProgressBar.test.ts`

**Strategy:** These are pre-existing failures unrelated to ai-accounts. Triage each:
- Tour machine state tests (5 failures) — likely XState v5 migration issue; update transition assertions
- TourOverlay timeout tests (4 failures) — likely jsdom/happy-dom timer behavior; use `vi.useFakeTimers()`
- TourProgressBar CSS test (1 failure) — hardcoded color assertion; update to match current tokens

### 5.5 Real subprocess login test (one backend, CI-safe)

**File:** `packages/core/tests/backends/test_claude_login_real.py` (new, marked `@pytest.mark.slow`)

**Strategy:** Run `claude --version` (fast, no auth needed) via `CliOrchestrator` to verify the real PTY path works end-to-end. Skip gracefully if `claude` is not installed:
```python
@pytest.mark.slow
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
async def test_real_claude_version_via_orchestrator(tmp_path):
    orch = CliOrchestrator(argv=["claude", "--version"], env={}, cwd=tmp_path)
    await orch.start()
    output = []
    async for chunk in orch.read_output():
        output.append(chunk)
    await orch.wait()
    assert orch.exit_code == 0
    assert any("claude" in c.lower() for c in output)
```

---

## Execution order

```
Phase 1 (Security) ──► Phase 2 (Reliability) ──► Phase 3 (Robustness) ──► Phase 4 (Infra)
                                                                               │
                                                                               ▼
                                                                         Phase 5 (Tests)
```

Phases 1 + 2 are release blockers and should be completed before any new `0.3.0-alpha.N` tag. Phases 3-5 can ship incrementally.

## Estimated effort

| Phase | Tasks | Est. time | Blocks release? |
|-------|-------|-----------|----------------|
| 1: Security | 4 | 1 day | Yes |
| 2: Reliability | 9 | 2 days | Yes |
| 3: Robustness | 6 | 1 day | No |
| 4: Infrastructure | 6 | 1-2 days | No |
| 5: Test coverage | 5 | 2-3 days | No |
| **Total** | **30** | **7-9 days** | |

## Files touched (summary)

**ai-accounts repo (25 files):**
- `packages/core/src/ai_accounts_core/login/cli_orchestrator.py` (5 fixes)
- `packages/core/src/ai_accounts_core/login/registry.py` (1 fix: add `close()`)
- `packages/core/src/ai_accounts_core/login/interactive.py` (logging)
- `packages/core/src/ai_accounts_core/backends/claude.py` (4 fixes)
- `packages/core/src/ai_accounts_core/backends/codex.py` (3 fixes)
- `packages/core/src/ai_accounts_core/backends/gemini.py` (4 fixes)
- `packages/core/src/ai_accounts_core/backends/opencode.py` (3 fixes)
- `packages/core/src/ai_accounts_core/cliproxy/manager.py` (2 fixes)
- `packages/core/src/ai_accounts_core/services/accounts.py` (1 fix)
- `packages/core/src/ai_accounts_core/adapters/storage_sqlite/storage.py` (1 fix: WAL)
- `packages/core/src/ai_accounts_core/__init__.py` (version fix)
- `packages/litestar/src/ai_accounts_litestar/routes/login.py` (1 fix)
- `packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py` (2 fixes)
- `packages/litestar/src/ai_accounts_litestar/errors.py` (1 fix)
- `packages/litestar/src/ai_accounts_litestar/app.py` (2 fixes: sweep + shutdown)
- `packages/litestar/src/ai_accounts_litestar/__init__.py` (version fix)
- `packages/ts-core/src/client/login-stream.ts` (1 fix)
- `packages/vue-headless/src/composables/useLoginSession.ts` (1 fix)
- `packages/vue-styled/src/index.ts` (version fix)
- 6 new test files

**Agented repo (4 files):**
- `backend/scripts/run_ai_accounts.py` (auth wiring)
- `frontend/src/main.ts` (token wiring)
- `frontend/src/composables/useTourMachine.ts` (initPromise fix)
- `justfile` (deploy recipe)
