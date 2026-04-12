# ai-accounts Silent Failures Audit

Audit date: 2026-04-11
Branches: `feat/0.3.0-alpha.1` (ai-accounts), `main` (Agented)

---

## CRITICAL Findings

### C-01: SSE `JSON.parse` failures silently dropped -- malformed events vanish

**File:** `/packages/ts-core/src/client/login-stream.ts:26-30`

```ts
try {
  yield JSON.parse(payload) as LoginEvent;
} catch {
  // malformed frame -- skip
}
```

**Issue:** When the Python process crashes mid-write, sends a partial JSON line, or emits an unexpected event type, the `catch {}` block silently discards it. The frontend receives zero indication that data was lost. If the server sends a `LoginFailed` event with a truncated JSON body, the user never learns the login failed -- the UI sits on "Connecting..." forever.

**Hidden errors:** `SyntaxError` from truncated JSON, but also any future bug where `JSON.parse` succeeds but produces a shape that is not a valid `LoginEvent` -- the `as LoginEvent` cast does no runtime validation.

**Severity:** CRITICAL

**Recommendation:** Log malformed frames to `console.warn` with the raw payload so developers can diagnose. Consider emitting a synthetic `LoginFailed` event after N consecutive parse failures so the UI never hangs indefinitely. Add runtime type validation (e.g., check `parsed.type` is a known event type) so invalid-but-parseable JSON does not silently produce garbage state.

---

### C-02: `useLoginSession.start()` has no try/catch -- network errors cause unhandled rejection

**File:** `/packages/vue-headless/src/composables/useLoginSession.ts:41-62`

```ts
async function start(id, flow, inputs) {
  accountId.value = id;
  status.value = 'running';
  // ...
  const { session_id } = await client.beginLogin(id, flow, inputs);
  sessionId.value = session_id;
  // ...
  for await (const event of client.streamLogin(id, session_id)) {
    dispatch(event);
    if (status.value !== 'running') return;
  }
}
```

**Issue:** If `client.beginLogin()` throws (network error, 4xx, 5xx), the promise rejects with `status` stuck at `'running'`. The user sees a permanent "Starting login session..." spinner. There is no catch block anywhere in this function. The caller in `AccountWizard.vue` does wrap in try/catch, but `console.warn` is the only feedback -- no UI state is updated to show an error.

Similarly, if `client.streamLogin()` throws on the initial fetch (e.g., session expired, 404), the same hang occurs.

**Hidden errors:** `TypeError` (network down), `ApiError` (server 4xx/5xx), `AbortError` (request cancelled).

**Severity:** CRITICAL

**Recommendation:** Wrap the entire `start()` body in try/catch. On failure, set `status.value = 'failed'`, populate `errorCode` and `errorMessage`, and emit a `login.failed` event.

---

### C-03: `LoginSessionRegistry.sweep()` fire-and-forget cancel tasks -- no shutdown await

**File:** `/packages/core/src/ai_accounts_core/login/registry.py:48-63`

```python
task = asyncio.create_task(entry.session.cancel())
self._pending_cancels.add(task)
task.add_done_callback(self._pending_cancels.discard)
```

**Issue:** Cancel tasks are tracked in `_pending_cancels` but the registry has no `close()` or `shutdown()` method. When the Litestar app shuts down (e.g., Ctrl-C in dev, SIGTERM in prod), these tasks are abandoned. If `session.cancel()` involves terminating a subprocess (which it does -- `CliOrchestrator.terminate()` + `wait()`), the subprocess becomes orphaned. The `done_callback` that discards from `_pending_cancels` can itself raise if called during interpreter shutdown.

Additionally, if `session.cancel()` raises an exception, the task's exception is never retrieved -- Python logs "Task exception was never retrieved" to stderr, but no structured error handling occurs.

**Hidden errors:** `ProcessLookupError`, `OSError`, any exception from session cleanup.

**Severity:** CRITICAL

**Recommendation:** Add an `async def close(self)` method that awaits all `_pending_cancels`. Register it as a Litestar `on_shutdown` hook. Add exception handling in the `done_callback` or use `task.add_done_callback` that logs exceptions.

---

### C-04: `asyncio.create_task(_reap())` in cliproxy route -- fire-and-forget with no error handling

**File:** `/packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py:101-110`

```python
async def _reap() -> None:
    try:
        await asyncio.wait_for(proc.wait(), timeout=300)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    finally:
        _ACTIVE_PROCS.pop(proc_id, None)

asyncio.create_task(_reap())
```

**Issue:** The task reference is never stored or awaited. If `_reap()` raises an unexpected exception (e.g., `ProcessLookupError` from `proc.kill()` if the process already exited between the timeout and the kill call), the exception is silently lost. The process entry remains in `_ACTIVE_PROCS` forever (the `finally` is the only cleanup, and it does run, but the error is still unlogged). On shutdown, the task is abandoned.

**Hidden errors:** `ProcessLookupError`, `OSError`, any exception from `proc.wait()` or `proc.kill()`.

**Severity:** CRITICAL

**Recommendation:** Store the task reference. Add a `try/except` around `proc.kill()` inside the `TimeoutError` handler. Consider adding a `done_callback` that logs exceptions.

---

## HIGH Findings

### H-01: `os._exit(127)` in child process after failed `execvpe` -- no I/O cleanup

**File:** `/packages/core/src/ai_accounts_core/login/cli_orchestrator.py:153-157`

```python
try:
    os.chdir(self._cwd)
    os.execvpe(self._argv[0], self._argv, env)
except Exception:  # pragma: no cover - child side
    os._exit(127)
```

**Issue:** After `pty.fork()`, the child process inherits the parent's file descriptors. When `os.chdir()` or `os.execvpe()` fails, `os._exit(127)` terminates the child immediately without flushing buffers or closing FDs. This is actually the correct behavior in a post-fork child (calling `sys.exit()` would run atexit handlers from the parent's state), but the `except Exception` catches everything including `KeyboardInterrupt` (which is `BaseException`, not `Exception`, so this is actually fine). The real concern is that the parent never learns *why* the child exited with 127 -- there is no logging or error message. The parent will see exit code 127 from `waitpid` but has no context about whether the binary was not found, the cwd did not exist, or something else failed.

**Hidden errors:** `FileNotFoundError` (binary not on PATH), `PermissionError` (not executable), `OSError` (cwd does not exist).

**Severity:** HIGH

**Recommendation:** Before calling `os._exit(127)`, write a diagnostic message to stderr (which is inherited from the parent and will be visible in logs): `os.write(2, f"ai-accounts: exec failed: {exc}\n".encode())`. This gives the parent and log viewers context about why the child died.

---

### H-02: `get_cliproxy_version()` -- bare `except Exception: pass`

**File:** `/packages/core/src/ai_accounts_core/cliproxy/manager.py:66-78`

```python
def get_cliproxy_version() -> str | None:
    path = shutil.which(_CLIPROXY_BINARY)
    if path is None:
        return None
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or result.stderr.strip()
    except Exception:
        pass
    return None
```

**Issue:** Any exception from `subprocess.run` -- including `OSError` (binary exists but cannot execute), `subprocess.TimeoutExpired` (process hangs), or `MemoryError` -- is silently swallowed. The caller receives `None`, which is indistinguishable from "binary not found".

**Hidden errors:** `TimeoutExpired`, `OSError`, `PermoryError`, `PermissionError`.

**Severity:** HIGH

**Recommendation:** Narrow the catch to `(subprocess.TimeoutExpired, OSError)` and log other exceptions.

---

### H-03: `ClaudeBackend.list_models()` -- `json.loads` crash on malformed output

**File:** `/packages/core/src/ai_accounts_core/backends/claude.py:251-264`

```python
if rc != 0:
    return []
raw: list[dict[str, Any]] = json.loads(stdout)
```

**Issue:** If the `claude models list --json` command exits with rc=0 but produces non-JSON output (e.g., a warning message followed by JSON, or a stack trace), `json.loads` raises `json.JSONDecodeError` which propagates up as an unhandled exception. The Gemini and Codex backends handle this correctly with a `try/except json.JSONDecodeError`, but Claude and OpenCode do not.

**Hidden errors:** `json.JSONDecodeError`, `KeyError` (if items lack `"id"` field).

**Severity:** HIGH

**Recommendation:** Add `try/except json.JSONDecodeError: return []` as done in the Gemini backend. Also wrap the list comprehension to handle missing keys.

---

### H-04: `shutil.rmtree(isolation_dir, ignore_errors=True)` -- deletion failures silently ignored

**File:** `/packages/core/src/ai_accounts_core/services/accounts.py:141`

```python
if isolation_dir.exists():
    shutil.rmtree(isolation_dir, ignore_errors=True)
```

**Issue:** If the isolation directory contains credential files, config, or socket files that cannot be deleted (permissions, in-use locks on macOS), the deletion silently fails. The backend record is deleted from the database but the filesystem artifacts remain. No log entry, no user feedback.

**Severity:** HIGH

**Recommendation:** Use `shutil.rmtree(isolation_dir)` in a try/except, log a warning on failure, and include the path and exception. The backend is deleted regardless, but the user/admin should know about orphaned directories.

---

### H-05: `_ClaudeCliBrowserSession.events()` finally block -- triple-silent-catch

**File:** `/packages/core/src/ai_accounts_core/backends/claude.py:103-112`

```python
finally:
    if self._orchestrator is not None:
        try:
            await self._orchestrator.terminate()
        except Exception:  # pragma: no cover - best-effort
            pass
        try:
            await self._orchestrator.wait()
        except Exception:  # pragma: no cover - best-effort
            pass
    self._done = True
```

**Issue:** Two bare `except Exception: pass` blocks swallow every possible error from subprocess termination and wait. If `wait()` hangs because `waitpid` blocks (e.g., zombie process), the coroutine never completes and the SSE stream hangs forever. If `terminate()` fails with `PermissionError` (shouldn't happen but can), the subprocess is never cleaned up.

The same pattern appears in `_ClaudeCliBrowserSession.cancel()` at line 119-122.

**Hidden errors:** `PermissionError`, `ChildProcessError`, `BlockingIOError`, `asyncio.CancelledError` (suppressing this prevents proper task cancellation).

**Severity:** HIGH

**Recommendation:** At minimum, log the exception. Critically, do NOT catch `asyncio.CancelledError` -- suppressing it breaks task cancellation semantics. Change to `except (OSError, ProcessLookupError):`.

---

### H-06: `cliproxy/login/begin` returns HTTP 201 with `status: "skipped"` or `status: "error"`

**File:** `/packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py:72-95`

```python
@post("/login/begin", status_code=201)
async def login_begin(self, data: _LoginBeginRequest) -> _LoginBeginResponse:
    # ...
    if info.error:
        return _LoginBeginResponse(
            status="error" if "not found" not in info.error else "skipped",
            message=info.error,
        )
    # ...
    if info.oauth_url is None:
        return _LoginBeginResponse(
            status="skipped",
            message="Proxy login did not produce an OAuth URL",
        )
```

**Issue:** Error conditions return HTTP 201 (Created) with a JSON body containing `status: "error"` or `status: "skipped"`. The TS client (`cliproxyLoginBegin`) checks `!r.ok` which only triggers on 4xx/5xx -- a 201 with `status: "error"` is treated as success. The frontend `AccountWizard.vue` must manually inspect the `status` field, which is fragile and violates HTTP semantics.

**Severity:** HIGH

**Recommendation:** Return HTTP 400 or 409 for error/skipped states. Reserve 201 for successful starts.

---

### H-07: `service_error_handler` catches non-`ServiceError` exceptions

**File:** `/packages/litestar/src/ai_accounts_litestar/errors.py:19-31`

```python
def service_error_handler(request, exc):
    if isinstance(exc, ServiceError):
        status = _STATUS_BY_CODE.get(exc.code, 500)
        return Response(
            content={"error": {"code": exc.code, "message": str(exc) or exc.code}},
            status_code=status,
        )
    return Response(
        content={"error": {"code": "internal_error", "message": str(exc)}},
        status_code=500,
    )
```

**Issue:** The fallback branch returns `str(exc)` to the client, which may contain internal stack information, file paths, or credential fragments (e.g., from a `RuntimeError` in the vault). This is registered only for `ServiceError` in `app.py`, so the fallback branch should theoretically never run -- but if it does (e.g., due to exception hierarchy changes), it leaks internals.

**Severity:** HIGH

**Recommendation:** The fallback branch should return a generic message like "An internal error occurred" and log the actual exception server-side.

---

## MEDIUM Findings

### M-01: `contextlib.suppress(ProcessLookupError)` in terminate/kill -- correct but unlogged

**File:** `/packages/core/src/ai_accounts_core/login/cli_orchestrator.py:231-238`

```python
async def terminate(self) -> None:
    if self._pid is None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(self._pid, signal.SIGTERM)
```

**Issue:** Suppressing `ProcessLookupError` is correct -- the process may have already exited. However, no log entry records that the process was already gone when we tried to terminate it. This makes debugging race conditions between process exit and explicit termination harder.

**Severity:** MEDIUM

**Recommendation:** Replace `suppress` with an explicit try/except that logs at DEBUG level: `logger.debug("PID %d already exited when SIGTERM sent", self._pid)`.

---

### M-02: `contextlib.suppress(OSError)` when closing master FD

**File:** `/packages/core/src/ai_accounts_core/login/cli_orchestrator.py:254-257`

```python
if self._master_fd is not None:
    with contextlib.suppress(OSError):
        os.close(self._master_fd)
    self._master_fd = None
```

**Issue:** Correct in principle (double-close or already-closed FD), but `OSError` also includes `PermissionError` and `EBADF` from a corrupted FD value. Narrowing to `OSError` is fine; just needs a debug log.

**Severity:** MEDIUM

---

### M-03: `CliOrchestrator._reader_task` created without error callback

**File:** `/packages/core/src/ai_accounts_core/login/cli_orchestrator.py:160`

```python
self._reader_task = asyncio.create_task(self._reader_loop())
```

**Issue:** The task reference is stored (good) and awaited in `wait()` (good). However, if `_reader_loop()` raises an unexpected exception (e.g., `MemoryError`, though unlikely), the exception surfaces only when `wait()` is called. If the caller never calls `wait()` (e.g., on cancel paths), the exception is silently lost with a "Task exception was never retrieved" warning.

**Severity:** MEDIUM

**Recommendation:** Add a `task.add_done_callback` that logs unexpected exceptions.

---

### M-04: `_GeminiOAuthDeviceSession.respond()` is a no-op

**File:** `/packages/core/src/ai_accounts_core/backends/gemini.py:118-119`

```python
async def respond(self, answer: PromptAnswer) -> None:
    pass
```

**Issue:** If the frontend sends a `respond` call for this session type, it silently does nothing. The user's action is swallowed without feedback. Same pattern in `_CodexOAuthDeviceSession.respond()` and `_CodexCliBrowserSession.respond()`.

**Severity:** MEDIUM

**Recommendation:** Either raise `NotImplementedError("device flow sessions do not accept responses")` or log a warning.

---

### M-05: `toError()` in TS client swallows JSON parse errors silently

**File:** `/packages/ts-core/src/client/index.ts:67-83`

```ts
async function toError(r: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = r.statusText;
  try {
    const body = (await r.json()) as { error?: { code?: string; message?: string } };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
    }
  } catch {
    // non-JSON body or empty -- stick with statusText
  }
```

**Issue:** This is acceptable behavior for error parsing -- falling back to `statusText` when the body is not JSON is reasonable. However, if the body is valid JSON but has an unexpected shape (e.g., `{detail: "..."}` from Litestar's default error handler), the error code and message fall back to generic values. The user sees "Not Found" instead of a useful message.

**Severity:** MEDIUM

**Recommendation:** Also check for `body.detail` (Litestar convention) and `body.message` as fallbacks.

---

### M-06: `AccountWizard.vue` login failure only goes to `console.warn`

**File:** `/packages/vue-styled/src/components/AccountWizard.vue:347-370`

```ts
async function startUnifiedLogin() {
  // ...
  try {
    // ...
    await loginSession.start(draftAccountId.value, flow, collectInputs(meta));
  } catch (e: unknown) {
    console.warn('[AccountWizard] login failed:', e);
  }
}
```

**Issue:** When login startup fails (network error, server error, invalid session), the error is logged to console but no UI state is updated. The wizard UI remains in the "login" step with status `running` but no progress. The user has no way to know something went wrong and no way to retry.

Combined with C-02 (no try/catch in `useLoginSession.start()`), the user sees a permanent spinner.

**Severity:** MEDIUM (elevated by C-02)

**Recommendation:** In the catch block, set `loginSession.status.value = 'failed'` or a local error ref, and display an error message in the UI with a retry button.

---

### M-07: `vue-headless/plugin.ts` event bus double-catch swallows all errors

**File:** `/packages/vue-headless/src/plugin.ts:18-31`

```ts
const emit = (event: AiAccountsEvent) => {
  try {
    onEvent(event);
  } catch (err) {
    try {
      onEvent({ type: 'internal.handler_error', error: ..., original: event });
    } catch {
      // swallow -- event bus must never propagate
    }
  }
};
```

**Issue:** If the `onEvent` handler throws on the error-reporting event itself, the original error is permanently lost. No `console.error`, no fallback logging. This is defensible for an event bus (it must not crash the app), but the inner catch should at minimum `console.error` the original error.

**Severity:** MEDIUM

**Recommendation:** Add `console.error('[ai-accounts] event handler crashed twice:', err, event)` in the inner catch.

---

### M-08: `proc.returncode or 0` masks negative return codes

**File:** Multiple backends (claude.py:302, gemini.py:485, codex.py:391, opencode.py:287)

```python
return proc.returncode or 0, stdout, stderr
```

**Issue:** If `proc.returncode` is `0` (success), this returns `0`. If it is `None` (process not yet terminated -- should not happen after `communicate()`), this returns `0`. If it is `-9` (killed by SIGKILL), `or 0` does NOT trigger because `-9` is truthy. So this is actually fine for negative values. However, the intent is unclear and the `None` case silently converts to success, which could mask bugs in `communicate()` implementations.

**Severity:** MEDIUM

**Recommendation:** Use explicit null handling: `return proc.returncode if proc.returncode is not None else -1, stdout, stderr`.

---

### M-09: `useTourMachine` -- multiple bare `catch {}` blocks

**File:** `/Users/neo/Developer/Projects/Agented/frontend/src/composables/useTourMachine.ts`

Lines 45, 61, 82, 103, 195 all have bare `catch {}` blocks that silently swallow errors from:
- `localStorage.getItem` / `JSON.parse` (line 45) -- corrupted storage
- `localStorage.setItem` (line 61) -- storage full
- `fetch` for instance-id (line 82) -- network error
- `fetch` for guard checks (line 103) -- network error  
- `createActor` with snapshot (line 195) -- incompatible snapshot

These are all individually defensible (tour is best-effort), but the complete absence of any logging means diagnosing tour issues in production requires reproducing them locally. At minimum, `console.debug` would help.

**Severity:** MEDIUM

**Recommendation:** Add `console.debug` or `console.warn` in each catch block.

---

### M-10: `start_cliproxy_login` -- process cleanup bare `except Exception: pass`

**File:** `/packages/core/src/ai_accounts_core/cliproxy/manager.py:219-224, 227-231`

```python
try:
    proc.kill()
    await proc.wait()
except Exception:
    pass
```

Two instances of this pattern. If `proc.kill()` or `proc.wait()` raises something unexpected (e.g., `asyncio.CancelledError`), it is swallowed. `asyncio.CancelledError` in particular must not be caught -- it breaks structured concurrency.

**Severity:** MEDIUM

**Recommendation:** Change to `except (OSError, ProcessLookupError):` or at minimum `except Exception as exc: logger.debug("cleanup error: %s", exc)`.

---

### M-11: SSE stream generator in `LoginController.stream()` -- no error handling around `session.events()`

**File:** `/packages/litestar/src/ai_accounts_litestar/routes/login.py:73-82`

```python
async def gen():
    try:
        async for event in session.events():
            yield {"event": "login", "data": msgspec.json.encode(event).decode()}
    finally:
        await registry.remove(session_id)
```

**Issue:** If `session.events()` raises an exception (e.g., `CliOrchestrator.start()` fails with `OSError`, or `msgspec.json.encode()` fails on an unexpected event type), the exception propagates through the SSE generator. Litestar may or may not handle this gracefully -- the client will see the SSE connection drop with no structured error event. The `finally` block does clean up the registry, but the client receives no `LoginFailed` event explaining what happened.

**Severity:** MEDIUM

**Recommendation:** Wrap in a broader try/except that yields a synthetic `LoginFailed` event before re-raising or closing.

---

### M-12: `LoginController.cancel()` -- returns 204 on nonexistent session

**File:** `/packages/litestar/src/ai_accounts_litestar/routes/login.py:103-108`

```python
async def cancel(self, ...) -> None:
    session = await account_service.login_registry.get(data.session_id)
    if session is None:
        return
    await session.cancel()
    await account_service.login_registry.remove(data.session_id)
```

**Issue:** If the session does not exist (already expired, already cancelled, typo in session_id), the endpoint returns 204 silently. The client has no way to know whether the cancel actually did anything. This is arguably idempotent (desired for cancel), but it also means a client with a stale or incorrect session_id will never learn about the problem.

**Severity:** MEDIUM (borderline LOW -- idempotent cancel is a valid design choice)

---

### M-13: `forward_cliproxy_callback` returns dict with `status: "error"` not HTTP error

**File:** `/packages/core/src/ai_accounts_core/cliproxy/manager.py:238-264`

```python
async def forward_cliproxy_callback(callback_url: str) -> dict:
    # ...
    except Exception as exc:
        return {"status": "error", "message": f"Failed to reach callback server: {exc}"}
```

**Issue:** This function returns in-band error signaling (a dict with `status: "error"`) rather than raising an exception. The caller in `CliproxyController.login_callback_forward()` passes it through to the HTTP response as 200 OK. The TS client will not throw because `r.ok` is true. The frontend must inspect the `status` field manually.

**Severity:** MEDIUM

**Recommendation:** Raise an exception so the Litestar error handler can return a proper 4xx/5xx.

---

### M-14: `BackendDetailPage.vue` -- `loadHealth()` and `loadOtherBackendAccounts()` failures totally silent

**File:** `/Users/neo/Developer/Projects/Agented/frontend/src/views/BackendDetailPage.vue:622-633, 722-741`

```ts
async function loadHealth() {
  try { /* ... */ } catch { /* Health data is supplementary */ }
}
async function loadOtherBackendAccounts() {
  try { /* ... */ } catch { /* Non-critical */ }
}
```

**Issue:** Both functions have empty catch blocks with comments justifying the silence. While the data is indeed supplementary, there is zero diagnostic output. If these endpoints consistently fail (wrong URL, auth issue, server crash), the developer will not know until they manually check the network tab.

**Severity:** MEDIUM

**Recommendation:** Add `console.debug` with the error.

---

## LOW Findings

### L-01: `_ClaudeCliBrowserSession.cancel()` catch on terminate swallows CancelledError

Already covered in H-05 but worth noting separately: catching `Exception` in `cancel()` at claude.py:121 will also catch `asyncio.CancelledError`, preventing proper task cancellation propagation.

### L-02: `notifyAiAccountsEvent` in useTourMachine.ts -- `.catch(() => {})` 

File: `useTourMachine.ts:470`. The promise chain's catch block swallows actor init failures. Acceptable for tour (best-effort) but should log.

### L-03: `AccountWizard.vue:408` -- `loginSession.cancel().catch(() => {})`

Cancel failures on unmount are swallowed. Acceptable for cleanup but a `console.debug` would help.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 4     | Silent SSE parse failures, unhandled rejections in login flow, fire-and-forget tasks with no shutdown cleanup |
| HIGH     | 7     | Silent child process failures, bare except:pass blocks, HTTP 201 on errors, potential credential leaks in error handler |
| MEDIUM   | 14    | Missing logging in catch blocks, no-op respond methods, in-band error signaling |
| LOW      | 3     | Minor catch-and-swallow in best-effort paths |

The most dangerous patterns are:
1. **The SSE parse failure silence (C-01)** combined with **missing error handling in useLoginSession (C-02)** creates a scenario where the user's login attempt silently hangs with no feedback.
2. **Fire-and-forget asyncio tasks (C-03, C-04)** that are never awaited on shutdown will orphan subprocesses in production.
3. **Bare `except Exception: pass` blocks** appear 8+ times in production code, hiding everything from permission errors to cancellation signals.
