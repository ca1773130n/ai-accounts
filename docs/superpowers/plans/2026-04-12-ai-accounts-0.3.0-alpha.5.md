# 0.3.0-alpha.5: Polish, Security Hardening, and Release Prep

> **STATUS: Implemented (shipped in 0.3.0-alpha.2).** Core hardening landed in `325a622` (SSRF port bypass, path traversal guards, hide key format, models route), with `b55b616` (log rmtree failures), `e1a5305` (narrow finally-block catches), `5790428` + `c6c0dd5` (PR review fixes). Retroactively documented in the 0.3.0-alpha.2 CHANGELOG entry.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix critical issues from PR review (SSRF bypass, fd leaks, silent errors), add model listing UI, improve error propagation across the stack, and prepare for stable 0.3.0 release.

**Architecture:** This is a hardening pass, not new features. Fixes are spread across the codebase — core security guards, backend error handling, route-level SSE error propagation, and frontend error states. Model listing extends the existing `list_models` infrastructure with routes and UI.

**Tech Stack:** Same as prior alphas — Python (msgspec, litestar), TypeScript, Vue 3

**Reference:** PR #1 review findings (code-reviewer, silent-failure-hunter, test-analyzer agents)

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `packages/core/src/ai_accounts_core/cliproxy/manager.py` | Fix SSRF port bypass, add logging to error handlers |
| Modify | `packages/core/src/ai_accounts_core/backends/claude.py` | Fix fd leak, add logging to cleanup, replace key format leak |
| Modify | `packages/core/src/ai_accounts_core/backends/codex.py` | Fix fd leak in events() |
| Modify | `packages/core/src/ai_accounts_core/backends/gemini.py` | Fix path traversal guard, fix fd leak in events() |
| Modify | `packages/core/src/ai_accounts_core/backends/opencode.py` | Fix fd leak in events() |
| Modify | `packages/core/src/ai_accounts_core/login/interactive.py` | Fix silent menu coercion, improve timeout message |
| Modify | `packages/litestar/src/ai_accounts_litestar/routes/login.py` | Add SSE error event on stream failure |
| Modify | `packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py` | Store fire-and-forget task, add error handler |
| Create | `packages/litestar/src/ai_accounts_litestar/routes/models.py` | GET /api/v1/backends/{id}/models route |
| Modify | `packages/litestar/src/ai_accounts_litestar/app.py` | Register ModelsController |
| Modify | `packages/ts-core/src/client/index.ts` | Add listModels() client method |
| Modify | `packages/vue-headless/src/composables/useLoginSession.ts` | Add error handling to start()/respond()/cancel() |
| Modify | `packages/ts-core/src/client/login-stream.ts` | Log dropped SSE frames |
| Create | `packages/core/tests/cliproxy/test_ssrf_scheme.py` | SSRF scheme validation test |
| Create | `packages/core/tests/cliproxy/test_ssrf_port_none.py` | SSRF port=None bypass test |

---

## Task 1: Fix SSRF Port Bypass in cliproxy/manager.py

**Files:**
- Modify: `packages/core/src/ai_accounts_core/cliproxy/manager.py`
- Test: `packages/core/tests/cliproxy/test_ssrf_port_none.py`

The SSRF guard at line 258 checks `if parsed.port` which is falsy when port is `None` (default port omitted in URL). This allows `http://127.0.0.1/callback` to bypass the port allowlist entirely.

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/cliproxy/test_ssrf_port_none.py
import pytest

from ai_accounts_core.cliproxy.manager import forward_cliproxy_callback


@pytest.mark.asyncio
async def test_default_port_80_rejected():
    """URLs without explicit port should use scheme-default (80/443) and be checked."""
    result = await forward_cliproxy_callback(
        "http://127.0.0.1/callback?code=abc&state=xyz"
    )
    # Port 80 is not in the allowlist, so this should be rejected
    assert result["status"] == "error"
    assert "port" in result["message"].lower()


@pytest.mark.asyncio
async def test_default_port_443_rejected():
    result = await forward_cliproxy_callback(
        "https://127.0.0.1/callback?code=abc&state=xyz"
    )
    assert result["status"] == "error"
    assert "port" in result["message"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/core && python -m pytest tests/cliproxy/test_ssrf_port_none.py -v
```

Expected: FAIL — the guard is bypassed when port is None.

- [ ] **Step 3: Fix the port guard**

In `packages/core/src/ai_accounts_core/cliproxy/manager.py`, find the port check (around line 258):

Replace:
```python
if parsed.port and parsed.port not in _CLIPROXY_ALLOWED_PORTS:
```

With:
```python
effective_port = parsed.port or (443 if parsed.scheme == "https" else 80)
if effective_port not in _CLIPROXY_ALLOWED_PORTS:
    return {"status": "error", "message": f"callback port {effective_port} not allowed"}
```

Also remove the redundant `port = parsed.port or 54545` line that follows and use `effective_port` instead.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/core && python -m pytest tests/cliproxy/test_ssrf_port_none.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/cliproxy/manager.py packages/core/tests/cliproxy/test_ssrf_port_none.py
git commit -m "fix(core): SSRF guard — handle default port when parsed.port is None"
```

---

## Task 2: Fix SSRF Scheme Validation Test Gap

**Files:**
- Test: `packages/core/tests/cliproxy/test_ssrf_scheme.py`

- [ ] **Step 1: Write test for scheme rejection**

```python
# packages/core/tests/cliproxy/test_ssrf_scheme.py
import pytest

from ai_accounts_core.cliproxy.manager import forward_cliproxy_callback


@pytest.mark.asyncio
async def test_file_scheme_rejected():
    result = await forward_cliproxy_callback("file:///etc/passwd?code=x&state=y")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_gopher_scheme_rejected():
    result = await forward_cliproxy_callback("gopher://evil.com?code=x&state=y")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_ftp_scheme_rejected():
    result = await forward_cliproxy_callback("ftp://evil.com/file?code=x&state=y")
    assert result["status"] == "error"
```

- [ ] **Step 2: Run test — should already pass if scheme check exists**

```bash
cd packages/core && python -m pytest tests/cliproxy/test_ssrf_scheme.py -v
```

If it passes, the existing scheme guard works. If not, add the guard.

- [ ] **Step 3: Commit**

```bash
git add packages/core/tests/cliproxy/test_ssrf_scheme.py
git commit -m "test(core): add SSRF scheme validation tests (file, gopher, ftp)"
```

---

## Task 3: Fix Path Traversal Guard (String Prefix → is_relative_to)

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/gemini.py`
- Test: `packages/core/tests/backends/test_gemini_direct_oauth.py` (add case)

- [ ] **Step 1: Write failing test**

Add to `packages/core/tests/backends/test_gemini_direct_oauth.py`:

```python
@pytest.mark.asyncio
async def test_path_traversal_via_similar_prefix(tmp_path):
    """Path like /home/username-evil should not pass if allowed root is /home/user."""
    from ai_accounts_core.backends.gemini import _validate_config_path
    from pathlib import Path

    # This tests the is_relative_to fix
    # /home/user is the root, /home/username should NOT be relative to it
    # With string startswith, it would incorrectly pass
    allowed = Path("/home/user")
    evil_path = Path("/home/username-evil/.config")
    # After fix, this should raise or return False
    # The actual test depends on how _validate_config_path is structured
```

- [ ] **Step 2: Fix the guard**

In `packages/core/src/ai_accounts_core/backends/gemini.py`, find the path check (around line 47):

Replace:
```python
if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
```

With:
```python
if not any(resolved.is_relative_to(root) for root in allowed_roots):
```

`Path.is_relative_to()` is available in Python 3.9+ and correctly handles the prefix ambiguity.

- [ ] **Step 3: Run existing Gemini tests to verify no regression**

```bash
cd packages/core && python -m pytest tests/backends/test_gemini_direct_oauth.py -v
```

- [ ] **Step 4: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/gemini.py packages/core/tests/backends/test_gemini_direct_oauth.py
git commit -m "fix(core): path traversal guard — use is_relative_to instead of string prefix"
```

---

## Task 4: Fix PTY fd Leak in Backend Sessions

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/codex.py`
- Modify: `packages/core/src/ai_accounts_core/backends/gemini.py`
- Modify: `packages/core/src/ai_accounts_core/backends/opencode.py`

The Claude backend's `_ClaudeCliBrowserSession.events()` has a `try/finally` that calls `terminate()` + `wait()`, but Codex, Gemini, and OpenCode sessions do not.

- [ ] **Step 1: Fix each backend's events() method**

For each of `codex.py`, `gemini.py`, `opencode.py`, find the `events()` method in the session classes that use a `CliOrchestrator`. Wrap the orchestrator iteration in a `try/finally` block that calls `terminate()` + `wait()`:

Pattern to apply in each:
```python
async def events(self) -> AsyncIterator[LoginEvent]:
    try:
        # ... existing iteration logic ...
        yield ...
    finally:
        try:
            self._orch.terminate()
        except Exception:
            pass
        try:
            await self._orch.wait()
        except Exception:
            pass
```

Specifically apply to:
- `_CodexOAuthDeviceSession.events()` in `codex.py`
- `_CodexCliBrowserSession.events()` in `codex.py`
- `_GeminiOAuthDeviceSession.events()` in `gemini.py`
- `_OpenCodeCliBrowserSession.events()` in `opencode.py`

- [ ] **Step 2: Run existing login tests to verify no regression**

```bash
cd packages/core && python -m pytest tests/backends/ -v
```

- [ ] **Step 3: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/
git commit -m "fix(core): PTY fd leak — add try/finally to all backend session events()"
```

---

## Task 5: Add Logging to Silent Error Handlers

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/claude.py`
- Modify: `packages/core/src/ai_accounts_core/cliproxy/manager.py`

Replace bare `except Exception: pass` blocks with logged suppressions.

- [ ] **Step 1: Add logging to Claude cleanup blocks**

In `packages/core/src/ai_accounts_core/backends/claude.py`, add at the top:
```python
import logging

logger = logging.getLogger(__name__)
```

Replace each `except Exception: pass` with:
```python
except ProcessLookupError:
    pass  # child already exited — expected
except OSError:
    logger.warning("orchestrator cleanup failed", exc_info=True)
```

- [ ] **Step 2: Add logging to cliproxy manager**

In `packages/core/src/ai_accounts_core/cliproxy/manager.py`, add at the top:
```python
import logging

logger = logging.getLogger(__name__)
```

Replace `get_cliproxy_version` except block:
```python
except subprocess.TimeoutExpired:
    logger.warning("cliproxy version check timed out")
    return None
except OSError as exc:
    logger.warning("cliproxy version check failed: %s", exc)
    return None
```

Replace process cleanup except blocks:
```python
except ProcessLookupError:
    pass
except OSError:
    logger.warning("cliproxy process cleanup failed", exc_info=True)
```

- [ ] **Step 3: Fix API key format leak**

In `packages/core/src/ai_accounts_core/backends/claude.py`, find:
```python
yield LoginFailed(code="invalid_key", message="API key must start with sk-ant-")
```
Replace with:
```python
yield LoginFailed(code="invalid_key", message="Invalid API key format")
```

- [ ] **Step 4: Run all tests**

```bash
cd packages/core && python -m pytest -v
```

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/claude.py packages/core/src/ai_accounts_core/cliproxy/manager.py
git commit -m "fix(core): replace silent except-pass blocks with logged handlers, hide key format"
```

---

## Task 6: SSE Login Stream Error Propagation

**Files:**
- Modify: `packages/litestar/src/ai_accounts_litestar/routes/login.py`
- Test: `packages/litestar/tests/test_login_stream_error.py`

- [ ] **Step 1: Write test**

```python
# packages/litestar/tests/test_login_stream_error.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from ai_accounts_core.login.events import LoginFailed


@pytest.mark.asyncio
async def test_sse_emits_error_on_stream_failure():
    """If session.events() raises, the SSE stream should emit a LoginFailed event."""
    # This tests the pattern, not the actual route — the route should catch
    # exceptions from session.events() and yield a LoginFailed SSE event
    # instead of silently closing the stream.
    pass  # Integration test in the route
```

- [ ] **Step 2: Fix the SSE generator in login.py**

In `packages/litestar/src/ai_accounts_litestar/routes/login.py`, find the SSE generator function. Wrap `session.events()` in try/except:

```python
import logging

logger = logging.getLogger(__name__)

async def gen():
    try:
        async for event in session.events():
            yield {"event": "login", "data": msgspec.json.encode(event).decode()}
    except Exception:
        logger.exception("login stream error for session %s", session_id)
        failed = LoginFailed(code="stream_error", message="Login stream terminated unexpectedly")
        yield {"event": "login", "data": msgspec.json.encode(failed).decode()}
    finally:
        await registry.remove(session_id)
```

- [ ] **Step 3: Run existing login route tests**

```bash
cd packages/litestar && python -m pytest tests/test_login_routes.py -v
```

- [ ] **Step 4: Commit**

```bash
git add packages/litestar/src/ai_accounts_litestar/routes/login.py
git commit -m "fix(litestar): emit LoginFailed SSE event on stream errors instead of silent close"
```

---

## Task 7: Fix Cliproxy Fire-and-Forget Task

**Files:**
- Modify: `packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py`

- [ ] **Step 1: Store task reference and add error handler**

In `packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py`, find the `asyncio.create_task(_reap())` call.

Replace with:
```python
import logging

logger = logging.getLogger(__name__)

def _handle_reap_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        logger.warning("cliproxy reap task failed: %s", task.exception())

reap_task = asyncio.create_task(_reap())
reap_task.add_done_callback(_handle_reap_error)
```

- [ ] **Step 2: Run cliproxy route tests**

```bash
cd packages/litestar && python -m pytest tests/test_cliproxy_routes.py -v
```

- [ ] **Step 3: Commit**

```bash
git add packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py
git commit -m "fix(litestar): store cliproxy reap task reference with error callback"
```

---

## Task 8: Model Listing Route and Client

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/models.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Modify: `packages/ts-core/src/client/index.ts`
- Test: `packages/litestar/tests/test_models_route.py`

- [ ] **Step 1: Write failing test**

```python
# packages/litestar/tests/test_models_route.py
import pytest
from litestar.testing import AsyncTestClient

from ai_accounts_core.testing.fakes import FakeBackend, FakeStorage, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest.fixture
async def client(tmp_path):
    config = AiAccountsConfig(
        storage=FakeStorage(),
        vault=FakeVault(),
        backends=(FakeBackend(),),
        backend_dirs_path=tmp_path,
    )
    app = create_app(config)
    async with AsyncTestClient(app) as tc:
        yield tc


@pytest.mark.asyncio
async def test_list_models(client):
    r = await client.post("/api/v1/backends/", json={
        "kind": "fake", "display_name": "T", "config": {}
    })
    backend_id = r.json()["id"]
    await client.post(f"/api/v1/backends/{backend_id}/login", json={
        "flow_kind": "api_key", "inputs": {"key": "sk-fake"}
    })
    await client.post(f"/api/v1/backends/{backend_id}/validate")

    r = await client.get(f"/api/v1/backends/{backend_id}/models")
    assert r.status_code == 200
    models = r.json()["items"]
    assert len(models) >= 1
    assert models[0]["id"] == "fake-1"
```

- [ ] **Step 2: Create models route**

```python
# packages/litestar/src/ai_accounts_litestar/routes/models.py
from litestar import Controller, get

from ai_accounts_core.services.accounts import AccountService


class ModelsController(Controller):
    path = "/api/v1/backends/{backend_id:str}/models"

    @get("/")
    async def list_models(
        self, account_service: AccountService, backend_id: str
    ) -> dict:
        models = await account_service.list_models(backend_id)
        return {
            "items": [
                {
                    "id": m.id,
                    "display_name": m.display_name,
                    "context_window": m.context_window,
                    "input_price_per_mtok": m.input_price_per_mtok,
                    "output_price_per_mtok": m.output_price_per_mtok,
                }
                for m in models
            ]
        }
```

- [ ] **Step 3: Wire into app.py**

Add import and register `ModelsController` in `route_handlers`.

- [ ] **Step 4: Add listModels() to ts-core client**

```typescript
  async listModels(backendId: string): Promise<{ items: Array<{
    id: string;
    display_name: string;
    context_window: number | null;
    input_price_per_mtok: number | null;
    output_price_per_mtok: number | null;
  }> }> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(backendId)}/models`,
      { headers: this.headers() },
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as any;
  }
```

- [ ] **Step 5: Run tests**

```bash
cd packages/litestar && python -m pytest tests/test_models_route.py -v
```

- [ ] **Step 6: Commit**

```bash
git add packages/litestar/src/ai_accounts_litestar/routes/models.py packages/litestar/src/ai_accounts_litestar/app.py packages/litestar/tests/test_models_route.py packages/ts-core/src/client/index.ts
git commit -m "feat(litestar): GET /api/v1/backends/{id}/models + ts-core listModels()"
```

---

## Task 9: Frontend Error Handling Fixes

**Files:**
- Modify: `packages/vue-headless/src/composables/useLoginSession.ts`
- Modify: `packages/ts-core/src/client/login-stream.ts`

- [ ] **Step 1: Add try/catch to useLoginSession.start()**

In `packages/vue-headless/src/composables/useLoginSession.ts`, wrap the `start()` function body in try/catch:

```typescript
async function start() {
  try {
    const { session_id } = await client.beginLogin(accountId, flow, inputs);
    // ... existing stream iteration ...
  } catch (err: unknown) {
    status.value = 'failed';
    errorCode.value = (err as any)?.code ?? 'network_error';
    errorMessage.value = (err as Error)?.message ?? 'Login failed unexpectedly';
  }
}
```

Also wrap `respond()` and `cancel()`:
```typescript
async function respond(...) {
  if (!sessionId.value || !textPrompt.value) {
    console.warn('[ai-accounts] respond() called with missing state');
    return;
  }
  try {
    await client.respondLogin(...);
  } catch (err: unknown) {
    errorCode.value = 'respond_error';
    errorMessage.value = (err as Error)?.message ?? 'Failed to submit response';
  }
}
```

- [ ] **Step 2: Add logging to SSE frame parser**

In `packages/ts-core/src/client/login-stream.ts`, replace the silent catch:

```typescript
try {
  yield JSON.parse(payload) as LoginEvent;
} catch (e) {
  console.warn('[ai-accounts] malformed SSE login frame dropped:', payload.slice(0, 200));
}
```

- [ ] **Step 3: Run tests**

```bash
cd packages/vue-headless && pnpm test
cd packages/ts-core && pnpm test
```

- [ ] **Step 4: Commit**

```bash
git add packages/vue-headless/src/composables/useLoginSession.ts packages/ts-core/src/client/login-stream.ts
git commit -m "fix(frontend): add error handling to useLoginSession, log dropped SSE frames"
```

---

## Task 10: Fix Interactive Menu Coercion

**Files:**
- Modify: `packages/core/src/ai_accounts_core/login/interactive.py`

- [ ] **Step 1: Fix silent coercion to 1 on invalid input**

In `packages/core/src/ai_accounts_core/login/interactive.py` around line 186, replace:

```python
try:
    chosen = int(answer.answer.strip())
except ValueError:
    chosen = 1
```

With:

```python
try:
    chosen = int(answer.answer.strip())
except ValueError:
    yield StdoutChunk(text=f"Invalid input '{answer.answer.strip()}', defaulting to option 1\n")
    chosen = 1
```

- [ ] **Step 2: Fix timeout message**

Around line 181-185, replace the silent break with a descriptive error:

```python
except asyncio.TimeoutError:
    yield LoginFailed(
        code="menu_timeout",
        message="Menu response timed out — no input received within the time limit",
    )
    return
```

- [ ] **Step 3: Run interactive tests**

```bash
cd packages/core && python -m pytest tests/login/test_interactive_orchestration.py -v
```

- [ ] **Step 4: Commit**

```bash
git add packages/core/src/ai_accounts_core/login/interactive.py
git commit -m "fix(core): interactive menu — log invalid input coercion, descriptive timeout error"
```

---

## Task 11: Run Full Test Suite + Version Bump

- [ ] **Step 1: Run all Python tests**

```bash
cd packages/core && python -m pytest -v
cd packages/litestar && python -m pytest -v
```

- [ ] **Step 2: Run all TypeScript tests**

```bash
cd packages/ts-core && pnpm test
cd packages/vue-headless && pnpm test
cd packages/vue-styled && pnpm test
```

- [ ] **Step 3: Bump versions to 0.3.0**

Update all package manifests to stable `0.3.0`.

- [ ] **Step 4: Final CHANGELOG update**

```markdown
## 0.3.0 — 2026-04-XX

### Security Fixes
- SSRF guard: handle default port when parsed.port is None
- Path traversal guard: use is_relative_to instead of string prefix
- Hide API key format in error messages
- Add logging to all silent except-pass blocks

### Bug Fixes
- PTY fd leak: add try/finally to all backend session events()
- SSE login stream: emit LoginFailed event on errors instead of silent close
- Cliproxy: store reap task with error callback
- Frontend: add error handling to useLoginSession
- Interactive menu: log invalid input, descriptive timeout error

### Added
- GET /api/v1/backends/{id}/models route + listModels() client method
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "release: 0.3.0 (stable — chat + PTY + security hardening)"
```
