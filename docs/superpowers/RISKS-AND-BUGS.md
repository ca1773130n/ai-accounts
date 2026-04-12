# RISKS-AND-BUGS.md

**Subject:** ai-accounts 0.3.0-alpha.2 — Security, Race Condition, and Bug Review
**Reviewed by:** Code Review Agent (claude-sonnet-4-6), 2026-04-11
**Scope:** `packages/core`, `packages/litestar` in `/Users/neo/Developer/Projects/ai-accounts`; Agented integration files in `/Users/neo/Developer/Projects/Agented/backend/scripts/run_ai_accounts.py`, `frontend/src/main.ts`, `frontend/src/views/BackendDetailPage.vue`, `frontend/src/composables/useTourMachine.ts`, `frontend/vite.config.ts`, `justfile`

---

### CRITICAL

**C-1: `_ClaudeCliBrowserSession.cancel()` races with `events()` finally — double `os.waitpid()` on same PID**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/claude.py:117–123`
- `cancel()` calls `terminate()` but not `wait()`. If `cancel()` is invoked (e.g. by TTL sweep) while `events()` is mid-loop, both paths eventually call `wait()` → two concurrent `os.waitpid()` calls on the same PID, which is undefined behavior and raises `ChildProcessError` on one side. Compare: `_GeminiOAuthDeviceSession.cancel()` correctly calls both `terminate()` and `wait()`.
- Fix: Add `await self._orchestrator.wait()` to `_ClaudeCliBrowserSession.cancel()`, guarded by `if self._orchestrator is not None`.

**C-2: `CliOrchestrator._reader_task` + thread-pool worker leak when `wait()` is not called**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/login/cli_orchestrator.py:162–175, 228–258`
- `terminate()` sends SIGTERM but never closes `master_fd` and never awaits `_reader_task`. `_read_once` runs in `run_in_executor`; it is blocked on `os.read(master_fd, 4096)` until the child-side PTY sends EIO — which only happens after the child exits. If `wait()` is never called, `master_fd` is never closed, the thread blocks indefinitely, and the executor thread pool drains over time.
- Fix: In `wait()`, cancel `_reader_task` before awaiting it. Add a `__del__` safeguard that closes `master_fd`.

**C-3: Client disconnect during SSE leaves subprocess running for up to 300 s — `gen()` finally removes session but does not cancel it**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/litestar/src/ai_accounts_litestar/routes/login.py:73–83`
- When Litestar cancels the SSE generator on client disconnect, `gen()`'s `finally` calls only `registry.remove(session_id)`. The orchestrator subprocess continues running. Any concurrent `/respond` POST that arrived in the same narrow window gets a 404 (session gone), so a `menu_response_timeout` wait (300 s default) runs out before the subprocess exits.
- Fix: In `gen()`'s `finally`, call `await session.cancel()` before or after `registry.remove()`.

**C-4: `forward_cliproxy_callback` proxies to arbitrary localhost port and path — SSRF**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/cliproxy/manager.py:238–264`; `/Users/neo/Developer/Projects/ai-accounts/packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py:119–127`
- `callback_url` comes from the POST body. The function parses `parsed.port` and `parsed.path` without any allowlist, then issues `httpx.GET http://127.0.0.1:{port}{path}`. Any authenticated (or in dev, unauthenticated) caller can redirect the sidecar to hit any localhost service — Flask admin routes, database management endpoints, etc.
- Fix: Assert `parsed.port == CLIPROXY_EXPECTED_PORT` (54545 or config-injected). Validate path starts with the expected OAuth callback prefix. Reject if either check fails.

**C-5: `_GeminiDirectOAuthSession._write_credentials` writes OAuth tokens to disk in plaintext, bypassing vault; path is user-controlled**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/gemini.py:223–250`
- `access_token`, `refresh_token`, and `id_token` are written as unencrypted JSON to `~/.gemini/oauth_creds.json` and `~/.cli-proxy-api/gemini-<email>.json`. File mode is default (0o644 on most systems). No vault is used. Additionally, `config_path_raw` from backend config is expanded by `os.path.expanduser` and used directly as a write path — a user who can PATCH a backend config can write the JSON to any path the server user can write.
- Fix: Store token bundle via vault like all other backends. Write to `isolation_dir` (already available). Validate `config_path` is within an allowed prefix. Set explicit `0o600` permissions.

---

### HIGH

**H-1: API key sessions block forever on `answers.get()` with no timeout; `cancel()` does not unblock them**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/claude.py:149`; same pattern in `gemini.py:267`, `opencode.py:143`, `gemini.py` (direct OAuth, line 267)
- Bare `await self._answers.get()` with no timeout. If the browser tab is closed after the `TextPrompt` is received, the coroutine blocks forever. TTL sweep calls `cancel()`, but `cancel()` for these sessions only sets `self._done = True` — it never puts a sentinel into `self._answers` to wake the blocked waiter.
- Fix: Use `asyncio.wait_for(..., timeout=300)`. In each `cancel()` method, `self._answers.put_nowait(PromptAnswer(prompt_id="__cancel__", answer=""))` to unblock any waiter.

**H-2: `respond()` after `events()` is done pushes sensitive data onto unread queue**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/claude.py:114–115`; all API-key session classes
- After `events()` returns and the session is removed from the registry, there is a narrow window where a concurrent `/respond` request still has a reference and calls `self._answers.put()`. No one is calling `get()`, so the answer (which may be an API key) lives in the queue indefinitely. `asyncio.Queue` has no max size, so repeated calls are also a slow memory leak.
- Fix: Check `self.done` in `respond()` and raise or no-op. Use `asyncio.Queue(maxsize=1)`.

**H-3: `_GeminiOAuthDeviceSession.events()` calls `wait()` without first calling `terminate()` — hangs on still-running process**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/gemini.py:108`; same in `opencode.py:99`, `codex.py` (corresponding line)
- After breaking from the `read_output()` loop (success or failure), the gemini CLI process may still be running. `await self._orchestrator.wait()` calls `os.waitpid()` in an executor thread with no timeout. If the process doesn't exit promptly, this hangs the event loop worker indefinitely.
- Fix: Add `await self._orchestrator.terminate()` before `await self._orchestrator.wait()` in all three backends' `events()` implementations.

**H-4: `start_cliproxy_login` temp directory is never cleaned up — one leak per call**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/cliproxy/manager.py:118–235`
- `_make_fake_open_dir()` creates a temp dir with two executable files. Neither the `imported`, `url is None`, nor the normal-success paths delete it. Every call to `POST /api/v1/cliproxy/login/begin` leaks one temp directory.
- Fix: Wrap with `tempfile.TemporaryDirectory()` as a context manager, or add explicit `shutil.rmtree(fake_dir, ignore_errors=True)` in all exit paths.

**H-5: PTY child is orphaned if parent process crashes before `wait()`**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/login/cli_orchestrator.py:146–157`
- After `pty.fork()`, the child gets no parent-death signal. If uvicorn/the sidecar is killed (SIGKILL, OOM), the child is re-parented to init and runs indefinitely. On Linux, `prctl(PR_SET_PDEATHSIG, SIGTERM)` in the child branch (before `execvpe`) prevents this.
- Fix: In the `pid == 0` branch, before `os.execvpe`, call `prctl(PR_SET_PDEATHSIG, SIGTERM)` on Linux. Document the limitation on macOS.

---

### MEDIUM

**M-1: API key value is transmitted in plain HTTP POST body (no TLS on loopback); Litestar debug mode may log request bodies**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/litestar/src/ai_accounts_litestar/routes/login.py:29–32`; `app.py:120`
- The `_RespondRequest.answer` field carries API keys over HTTP to `127.0.0.1:20001`. `debug=True` is set when `env="development"` (the current Agented configuration). Litestar does not log request bodies by default, but any custom access-log middleware or Litestar plugin that logs requests will capture the key. Confirm debug does not log bodies in deployment.
- Fix: Verify Litestar debug mode logging policy. Consider a dedicated `/respond/secret` endpoint annotated to skip logging. Document that the sidecar must not be exposed beyond loopback.

**M-2: `NoAuth` adapter used in all Agented deployments — sidecar endpoints are unauthenticated**
- File: `/Users/neo/Developer/Projects/Agented/backend/scripts/run_ai_accounts.py:32`
- `auth=NoAuth()` with `env="development"` bypasses the production guard. All `/api/v1/*` routes — create/delete backends, login, cliproxy — are accessible without credentials. The `NOTE: token is not wired yet` comment in `main.ts` acknowledges this.
- Fix: Wire the existing `ApiKeyAuth` adapter to require the same API key as Flask. Mark as a pre-release blocker.

**M-3: `config_path` path traversal in Gemini backend (also covered under C-5)**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/gemini.py:228–231`
- Standalone note separate from the vault issue: any user with write access to `PATCH /api/v1/backends/{id}` can set `config.config_path` to a path like `"../../etc"` and the credential write will target that path.

**M-4: `useTourMachine` `initPromise` never reset on rejection — silent no-op forever after init failure**
- File: `/Users/neo/Developer/Projects/Agented/frontend/src/composables/useTourMachine.ts:219–220`
- If `initActor()` rejects, `initPromise` holds a rejected Promise. All subsequent calls to `useTourMachine()` skip re-init. Subscriptions fail silently; `send()`, `startTour()`, `nextStep()` all no-op with no error.
- Fix: Add `.catch(() => { initPromise = null })` after assigning `initPromise = initActor()`.

**M-5: Vite proxy order: `/api/v1` goes to sidecar; if sidecar is down all wizard API calls fail — `just deploy` never starts the sidecar**
- File: `/Users/neo/Developer/Projects/Agented/frontend/vite.config.ts:27–34`; `/Users/neo/Developer/Projects/Agented/justfile:86–93`
- The `deploy` recipe starts Flask and Vite but not the ai-accounts sidecar. Any request to `/api/v1/*` will get "connection refused" on `:20001`. There is no fallback. The justfile has a `dev-ai-accounts` recipe but it is not included in `deploy`.
- Fix: Add the sidecar to the `deploy` recipe. Add a health check for `:20001` similar to the existing Flask readiness check.

---

### LOW

**L-1: `SqliteStorage` shares a single connection — no WAL mode, write serialisation under concurrent SSE streams**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/adapters/storage_sqlite/storage.py:348–377`
- Single `aiosqlite.Connection` used for all repos. `PRAGMA journal_mode = WAL` is not set. Concurrent writes fully serialise. Safe but a latency risk when multiple login sessions are active.
- Fix: Add `await conn.execute("PRAGMA journal_mode = WAL")` in `_ensure_conn`.

**L-2: `_ACTIVE_PROCS` in `cliproxy.py` uses `id(proc)` as key — address reuse after GC can overwrite entries**
- File: `/Users/neo/Developer/Projects/ai-accounts/packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py:52, 98`
- Python's `id()` returns the object's memory address, which can be reused after GC. A new process object can receive the same address as a previously reaped one, silently overwriting the `_ACTIVE_PROCS` entry and orphaning the old reaper task.
- Fix: Use `str(uuid.uuid4())` as the key instead.

---

**Key files referenced:**
- `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/login/cli_orchestrator.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/login/interactive.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/login/registry.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/claude.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/gemini.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/backends/opencode.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/core/src/ai_accounts_core/cliproxy/manager.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/litestar/src/ai_accounts_litestar/routes/login.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py`
- `/Users/neo/Developer/Projects/ai-accounts/packages/litestar/src/ai_accounts_litestar/app.py`
- `/Users/neo/Developer/Projects/Agented/backend/scripts/run_ai_accounts.py`
- `/Users/neo/Developer/Projects/Agented/frontend/src/composables/useTourMachine.ts`
- `/Users/neo/Developer/Projects/Agented/frontend/vite.config.ts`
- `/Users/neo/Developer/Projects/Agented/justfile`