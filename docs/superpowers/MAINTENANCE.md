# ai-accounts Maintenance Guide

Last updated: 2026-04-11

This guide covers operational knowledge for maintaining the ai-accounts system
across the `ai-accounts` monorepo (branch `feat/0.3.0-alpha.1`) and the
`Agented` consumer (branch `main`).

---

## 1. Dependency Inventory

### 1.1 Python: ai-accounts-core (0.3.0a2)

| Dependency      | Constraint   | Notes |
|-----------------|-------------|-------|
| `msgspec`       | `>=0.18`    | (a) Pre-1.0. API has stabilized but minor breaking changes are possible. (c) No upper bound. |
| `aiosqlite`     | `>=0.20`    | (a) Pre-1.0. (c) No upper bound. |
| `cryptography`  | `>=43.0`    | Mature, stable. (c) No upper bound -- major bumps occasionally drop old Python versions. |
| `httpx`         | `>=0.27`    | (a) Pre-1.0. (c) No upper bound. (d) Also used by Agented backend (`>=0.28.1`) and duplicated conceptually with JS `fetch` in ts-core. |

### 1.2 Python: ai-accounts-litestar (0.3.0a2)

| Dependency                | Constraint              | Notes |
|---------------------------|------------------------|-------|
| `ai-accounts-core`        | workspace (dev), `==0.3.0a2` (Agented) | (b) Pinned exactly in Agented's pyproject.toml -- must bump on every release. |
| `litestar[standard]`      | `>=2.12`               | (c) No upper bound. Litestar is pre-1.0 historically but now >= 2.x and stable. |

### 1.3 Python: Workspace dev dependencies (root pyproject.toml)

| Dependency       | Constraint   | Notes |
|------------------|-------------|-------|
| `pytest`         | `>=8.0`     | |
| `pytest-asyncio` | `>=0.24`    | (a) Pre-1.0. |
| `pytest-cov`     | `>=5.0`     | |
| `hypothesis`     | `>=6.100`   | |
| `mypy`           | `>=1.11`    | |
| `ruff`           | `>=0.6`     | (a) Pre-1.0. Frequently breaking lint rule changes. |
| `httpx`          | `>=0.27`    | Test HTTP client. |

### 1.4 Python: Agented backend consumer

| Dependency                 | Constraint       | Notes |
|---------------------------|-----------------|-------|
| `ai-accounts-core`        | `==0.3.0a2`     | (b) Exactly pinned. Must be bumped with each ai-accounts release. |
| `ai-accounts-litestar`    | `==0.3.0a2`     | (b) Exactly pinned. Same. |
| `cryptography`            | `>=41.0.0`      | Also a transitive dep of ai-accounts-core (>=43.0). The lower bound here (41.0) is less restrictive -- ai-accounts-core's >=43.0 wins at resolve time, but the discrepancy should be harmonized. |
| `httpx`                   | `>=0.28.1`      | Overlaps with ai-accounts-core's >=0.27. |
| `litestar`                | Transitive only  | Pulled in by ai-accounts-litestar. |

### 1.5 TypeScript: @ai-accounts/ts-core (0.3.0-alpha.2)

No runtime dependencies. Zero-dep package that uses the platform `fetch` API.
Build-time: `tsup`, `typescript`, `vitest`.

### 1.6 TypeScript: @ai-accounts/vue-headless (0.3.0-alpha.2)

| Dependency                | Constraint        | Notes |
|---------------------------|------------------|-------|
| `@ai-accounts/ts-core`   | `workspace:*`    | |
| `vue` (peer)              | `^3.4.0`         | |

Dev: `@vue/test-utils ^2.4.0`, `happy-dom ^15.0.0` (a: pre-1.0).

### 1.7 TypeScript: @ai-accounts/vue-styled (0.3.0-alpha.2)

| Dependency                    | Constraint        | Notes |
|-------------------------------|------------------|-------|
| `@ai-accounts/ts-core`       | `workspace:*`    | |
| `@ai-accounts/vue-headless`  | `workspace:*`    | |
| `vue` (peer)                  | `^3.4.0`         | |

Dev: `vite ^5.4.0`, `@vitejs/plugin-vue ^5.1.0`, `vue-tsc ^2.1.0`,
`@vue/test-utils ^2.4.0`, `happy-dom ^15.0.0`.

### 1.8 Workspace root (JS)

Dev-only: `@changesets/cli ^2.30.0`, `@types/node ^22.0.0`,
`@typescript-eslint/* ^8.5.0`, `@vitest/coverage-v8 ^2.1.0`,
`eslint ^9.10.0`, `openapi-typescript ^7.13.0`, `tsup ^8.3.0`,
`typescript ^5.5.0`, `vitest ^2.1.0`.

### 1.9 Flagged Issues

**(a) Pre-1.0 / may break:**
- `msgspec` (0.18+) -- serialization core; a break here is high-impact
- `aiosqlite` (0.20+) -- storage layer
- `httpx` (0.27+/0.28+) -- used in both Python and conceptually duplicated in JS
- `pytest-asyncio` (0.24+) -- test infra
- `ruff` (0.6+) -- lint/format
- `happy-dom` (15.0+) -- JS test env

**(b) Pinned too tightly:**
- Agented pins `ai-accounts-core==0.3.0a2` and `ai-accounts-litestar==0.3.0a2` exactly.
  Every ai-accounts release requires a corresponding Agented pyproject.toml bump.
  Consider using `~=0.3.0a2` (compatible release) once stable.

**(c) Missing upper bounds:**
- Every ai-accounts Python dependency uses only a floor (`>=`). A new major
  release of `litestar`, `cryptography`, or `msgspec` could break without warning.
  Consider adding `<N+1` caps for `cryptography` and `litestar` at minimum.

**(d) Python/JS overlap:**
- `httpx` (Python) vs `fetch` (JS): both used for HTTP to the same sidecar.
  Not a problem per se, but behavior differences (timeouts, redirect handling,
  error shapes) can cause parity bugs. The `cliproxy/manager.py` module uses
  `httpx.AsyncClient` for OAuth callback forwarding; the JS side uses `fetch`
  for all routes.

---

## 2. Upgrade Paths

### 2.1 Current state: 0.3.0-alpha.2

Alpha.1 shipped the wizard + login layer. Alpha.2 is the current published
version on PyPI/npm. Per the spec at
`docs/superpowers/specs/2026-04-11-ai-accounts-0.3.0-design.md`:

### 2.2 Alpha sequence

| Alpha   | Scope                     | Status       |
|---------|---------------------------|-------------|
| alpha.1 | Wizard + Login (SSE)      | Shipped     |
| alpha.2 | Chat (conversations, SSE) | Published (packages versioned), code not yet in ai-accounts repo |
| alpha.3 | PTY (WebSocket sessions)  | Planned     |

**alpha.2 deliverables (chat):**
- `ai-accounts-sessions-core` package (new): `ConversationService`, `MessageStore`, SSE helpers
- SQLite schema additions: `conversations`, `messages` tables (already present in schema.sql as `chat_sessions` / `chat_messages`)
- Routes: `/api/v1/conversations/*`
- `@ai-accounts/vue-sessions/ChatPanel.vue`, `ChatMessage.vue`
- Agented milestone: BackendDetailPage chat drawer uses packaged `<ChatPanel>`

**alpha.3 deliverables (PTY):**
- `ai-accounts-sessions-core/pty/` -- port of Agented's `pty_service.py`
- Litestar WebSocket handler at `/ws/pty/{session_id}`
- ts-core `PtySocket` client (reconnect, backpressure)
- `@ai-accounts/vue-sessions/TerminalView.vue` with xterm.js
- Vite proxy config needs `ws: true` for `/ws/*`
- CORS config for WebSocket origins (see section 5.4)

### 2.3 What can change in alphas vs stable

**Alphas (0.3.0-alpha.N):**
- Any type, route, event name, or protocol method may change
- Wire protocol version stays at 1 but fields may be added/removed
- SQLite schema may gain tables/columns (no destructive migrations yet)
- Python `BackendProtocol` signature may evolve (it did between alpha.1 and alpha.2)

**Stable (0.3.0):**
- Contract freeze point. Everything listed in section 6 becomes the stable API.
- Breaking changes require 0.4.0.
- Additive changes (new event types, new optional fields, new routes) are allowed in 0.3.x patches.

### 2.4 0.3.0-alpha.2 -> 0.3.0 stable

1. Complete alpha.3 (PTY) implementation
2. Freeze all contracts: types, events, protocols, routes
3. Fix the `__version__` mismatch (`core/__init__.py` still says `"0.2.2"` but packages are versioned `0.3.0a2`)
4. Run full Agented verification (`just build`, backend pytest, frontend vitest)
5. Manual E2E: fresh clone -> onboarding -> Claude /login -> chat -> interactive terminal
6. Finalize docs, changelog, migration guide
7. Yank 0.2.x npm/PyPI tags with deprecation notice
8. Publish 0.3.0 to npm and PyPI

### 2.5 0.3.0 -> 0.4.0

Per the spec, 0.4.0 is the next major version allowing breaking changes.
Potential scope:
- Multi-user auth (OIDC adapter)
- Cloud storage adapters (Postgres, DynamoDB)
- Telemetry / structured metrics
- Schema migrations with version tracking
- Vault key rotation implementation (currently `NotImplementedError`)

---

## 3. Testing Gaps

### 3.1 Modules with zero or minimal test coverage

**ai-accounts-core:**

| Module | Test coverage | Notes |
|--------|-------------|-------|
| `login/interactive.py` | Indirect only | The `run_interactive_cli_login` async generator is exercised only through `test_cli_orchestrator.py` and backend login tests, not directly. Menu parsing, idle triggers, and success-grace logic have no dedicated tests. |
| `login/cli_orchestrator.py` | `test_manager.py` covers cliproxy, `test_cli_orchestrator.py` exists | The PTY-based orchestrator is hard to test without a real terminal. `parse_menu_options` and `strip_ansi` have tests but `start()`, `poll_output()`, `send_menu_selection()` do not. |
| `cliproxy/manager.py` | `test_cliproxy_routes.py` (litestar) | The module-level functions (`install_cliproxy`, `start_cliproxy_login`, `forward_cliproxy_callback`) are tested only through route integration tests, not directly. The `_make_fake_open_dir` helper has no test. |
| `domain/pty.py` | None | Domain types for PTY (placeholder for alpha.3). |
| `domain/chat.py` | Tested via `test_sqlite_storage.py` | No dedicated domain-level tests. |
| `domain/principal.py` | Tested via `test_auth_adapters.py` | No dedicated tests. |
| `services/onboarding.py` | `test_onboarding_service.py` + `test_onboarding_routes.py` | Covered. |
| `backends/claude.py` | `test_claude_backend.py` + `backends/test_claude_login.py` | `chat()` and `pty()` raise `NotImplementedError` -- tested that they do, but no real coverage. |
| `backends/codex.py` | `test_codex_backend.py` + `backends/test_codex_login.py` | Same as claude. |
| `backends/gemini.py` | `test_gemini_backend.py` + `backends/test_gemini_login.py` + `backends/test_gemini_direct_oauth.py` | Same as claude. Direct OAuth session has dedicated tests. |
| `backends/opencode.py` | `test_opencode_backend.py` + `backends/test_opencode_login.py` | Same as claude. |
| `adapters/auth_apikey.py` | `test_auth_adapters.py` | Covered. |
| `adapters/auth_noauth.py` | `test_auth_adapters.py` | Covered. |

**ai-accounts-litestar:**

| Module | Test coverage | Notes |
|--------|-------------|-------|
| `routes/login.py` | `test_login_routes.py` | The SSE `/stream` endpoint is the hardest to test. See section 3.2. |
| `routes/cliproxy.py` | `test_cliproxy_routes.py` | Covered but depends on mocking subprocess. |
| `errors.py` | `test_config_guard.py` | Covered indirectly. |
| `dto.py` | Tested via route tests | No dedicated DTO tests. |

**TypeScript packages:**

| Module | Test file | Notes |
|--------|-----------|-------|
| `ts-core/client/index.ts` | `client.test.ts` | Covered. |
| `ts-core/client/login-stream.ts` | `login-stream.test.ts` | Covered. |
| `ts-core/events.ts` | No dedicated test | Type-only file, tested indirectly. |
| `ts-core/machines/accountWizard.ts` | `accountWizard.test.ts` | Covered. |
| `ts-core/machines/onboardingFlow.ts` | `onboardingFlow.test.ts` | Covered. |
| `ts-core/protocol/wire.ts` | No test | Generated file, type-only. |
| `vue-headless/plugin.ts` | `plugin.test.ts` | Covered. |
| `vue-headless/composables/*` | Respective test files | Covered. |
| `vue-styled/*` | Respective test files | Covered. |

### 3.2 SSE stream integration test (Litestar AsyncTestClient timing issue)

The `test_onboarding_full_flow` in Agented's
`backend/tests/integration/test_ai_accounts_proxy.py` is marked `@pytest.mark.xfail`
with the following reason:

> "alpha.1 onboarding login switched to the begin_login/stream/respond flow --
> the old synchronous FakeBackend api_key path no longer satisfies finalize().
> Needs a rewrite against useLoginSession-style streaming; tracked as follow-up
> to T25-28."

The core issue: the `AsyncTestClient` in Litestar cannot easily consume SSE
streams in the same event loop as the test function. The login flow requires:
1. `POST /login/begin` -> get `session_id`
2. `GET /login/stream?session_id=...` (SSE) -> consume events
3. `POST /login/respond` -> answer prompts (from a separate "task")
4. SSE stream yields `LoginComplete`

Steps 2 and 3 must happen concurrently, which `AsyncTestClient` does not
facilitate without `asyncio.gather` or background tasks. The test was reduced
to a smoke test that only verifies the first two steps succeed and the
`xfail` marker documents the gap.

**To fix:** Use `asyncio.create_task` to run the SSE consumer and respond
call concurrently within the test, or switch to a real uvicorn subprocess
with httpx for the integration test.

### 3.3 Tour-machine test failures (Agented frontend)

The `useTourMachine.test.ts` file at
`frontend/src/composables/__tests__/useTourMachine.test.ts` has 11 pre-existing
test failures. These are in Agented, not ai-accounts, but affect the
`just build` / `npm run test:run` verification gate.

The failures are related to xstate actor state transitions and mock setup for
the tour machine, not directly to ai-accounts. However, they block the
verification criteria listed in CLAUDE.md ("all three must pass").

### 3.4 Backends without login tests

All four backends (claude, codex, gemini, opencode) have login tests in
`packages/core/tests/backends/`:
- `test_claude_login.py`
- `test_codex_login.py`
- `test_gemini_login.py` + `test_gemini_direct_oauth.py`
- `test_opencode_login.py`

However, these test the `LoginSession` event sequence with mocked
`CliOrchestrator` -- they do **not** test actual CLI invocation. The
`cli_browser` flow for each backend requires a real PTY and a real CLI binary,
which cannot run in CI without the CLI installed.

The `FakeBackend` in `testing/fakes.py` provides a deterministic test double
but its `api_key` flow behavior diverged from the real backends during the
alpha.1 rewrite (hence the xfail in Agented's integration test).

---

## 4. Observability

### 4.1 Health endpoint

`GET /health` on the Litestar sidecar (port 20001) returns:

```json
{"status": "ok", "version": "<core __version__>"}
```

**Known issue:** `core/__init__.py` has `__version__ = "0.2.2"` while the
package is actually version `0.3.0a2`. The health endpoint reports the stale
version string.

### 4.2 Current logging patterns

The codebase uses `logging.getLogger(__name__)` in:
- `ai_accounts_core/adapters/vault_envkey/vault.py` -- logs a warning when
  no vault key is set (dev fallback derivation)
- `ai_accounts_core/login/cli_orchestrator.py` -- `logger = logging.getLogger(__name__)`
  declared but used sparingly

**What gets logged during login:**
- Vault: warns if `AI_ACCOUNTS_VAULT_KEY` is unset (dev mode only)
- CLI orchestrator: no login-specific log lines currently
- Litestar: standard request/response logging from the framework

**What does NOT get logged:**
- Login session creation (begin_login)
- Login session completion/failure
- Prompt/respond cycles
- Session registry sweeps (stale session cleanup)
- Subprocess spawn/terminate events
- Credential storage events

### 4.3 Tracing a stuck session

If a login session appears stuck:

1. Check the `LoginSessionRegistry` -- sessions have a configurable TTL
   (default 600s / 10 minutes). After TTL, `sweep()` cancels and removes them.
2. The registry is in-memory only (no persistence). If the sidecar process
   restarts, all active login sessions are lost.
3. Check for orphan PTY child processes: `CliOrchestrator` uses `pty.fork()`
   which creates real OS processes. If `cancel()` or `terminate()` is not
   called (e.g., sidecar crashes), the child process becomes orphaned.
4. To manually list orphan processes:
   ```bash
   ps aux | grep -E 'claude|opencode|gemini|codex' | grep -v grep
   ```

### 4.4 Suggested additions

**Structured logging:**
Add structured JSON logging to all login lifecycle events:
```python
logger.info("login.session_created", extra={
    "session_id": session.session_id,
    "backend_kind": session.backend_kind,
    "flow_kind": session.flow_kind,
})
```

**Metrics (recommended for production):**
- `ai_accounts_login_attempts_total` (counter, labels: backend_kind, flow_kind)
- `ai_accounts_login_success_total` (counter, labels: backend_kind, flow_kind)
- `ai_accounts_login_failure_total` (counter, labels: backend_kind, flow_kind, error_code)
- `ai_accounts_login_duration_seconds` (histogram, labels: backend_kind, flow_kind)
- `ai_accounts_active_sessions_gauge` (gauge, labels: kind [chat/pty/login])
- `ai_accounts_cli_spawn_duration_seconds` (histogram, labels: backend_kind)
- `ai_accounts_orphan_subprocess_count` (gauge)

**Alerting:**
- Alert on `orphan_subprocess_count > 0` sustained for > 5 minutes
- Alert on `login_failure_total` rate spike (e.g., > 5 failures in 1 minute)
- Alert on `active_sessions_gauge{kind=login}` exceeding TTL threshold count
- Alert on health endpoint returning non-200

---

## 5. Deployment Considerations

### 5.1 Vault key management

The `AI_ACCOUNTS_VAULT_KEY` environment variable provides the AES-256 key for
encrypting backend credentials at rest.

**Format:** Base64-encoded 32-byte key.

**Generate a key:**
```bash
python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
```

**Behavior by environment:**
- `production`: **Required.** The app refuses to start without it (raises `RuntimeError`).
- `development`: **Optional.** If unset, a deterministic dev-only fallback key is
  derived from a hardcoded seed. A warning is logged. This key is not secret and
  must never be used in production.

**Key rotation:** `EnvKeyVault.rotate()` raises `NotImplementedError`. To rotate
keys today: re-encrypt all credentials manually. This is tracked as tech debt
(see section 7).

**Operational notes:**
- The key ID is always `"envkey://v1"` -- there is no multi-key support.
- Ciphertext includes a 1-byte envelope version, 12-byte nonce, and AESGCM
  ciphertext with AAD bound to `{"backend_id": "..."}`.
- Changing the vault key without re-encrypting credentials makes all stored
  credentials unrecoverable.

### 5.2 Sidecar lifecycle

**Who starts it:**
- Development: `just dev-ai-accounts` runs `uv run python scripts/run_ai_accounts.py`
  which starts uvicorn on `127.0.0.1:20001`.
- `just dev-all` runs Flask (:20000), Litestar (:20001), and Vite (:3000) in parallel.
- Production (`just deploy`): currently does NOT start the sidecar -- only Flask
  and Vite. The sidecar must be started separately.

**Who restarts it if it crashes:**
- Nobody. There is no process manager configured for the sidecar.
- `just kill` will kill processes on ports 3000, 20000, and 20001.

**Recommended production setup:**
- Use systemd, supervisord, or Docker Compose to manage the sidecar as a
  separate unit with automatic restart.
- Configure health checks against `GET /health` on port 20001.
- Set `restart: always` or equivalent.

**Startup order:**
- The sidecar runs `storage.migrate()` on startup (Litestar `on_startup` hook).
  It creates/migrates the SQLite database. No dependency on Flask.
- Flask (Agented) does not depend on the sidecar at startup, but frontend
  requests to `/api/v1/*` will fail if the sidecar is down.

### 5.3 SQLite concurrency

**Single-writer constraint:**
- `aiosqlite` wraps SQLite's synchronous API in a background thread.
- SQLite allows only one writer at a time. The sidecar is single-process, so
  this is fine for normal operation.
- Running multiple sidecar instances against the same `.db` file will cause
  `SQLITE_BUSY` errors.

**WAL mode:**
- WAL mode is **not** currently enabled. The storage adapter does
  `PRAGMA foreign_keys = ON` but does not set `PRAGMA journal_mode = WAL`.
- Enabling WAL would allow concurrent reads during writes and is recommended
  for production: add `await conn.execute("PRAGMA journal_mode = WAL")` to
  `SqliteStorage._ensure_conn()`.

**Database location:**
- Development: `./ai_accounts.db` relative to the backend working directory.
- The path is set in `scripts/run_ai_accounts.py` via `SqliteStorage("./ai_accounts.db")`.
- For production, use an absolute path and ensure the directory is on a local
  filesystem (not NFS).

### 5.4 CORS config for WebSocket (alpha.3)

The current `AiAccountsConfig` has a `cors_origins` tuple used for HTTP CORS
via Litestar's `CORSConfig`. WebSocket connections in alpha.3 will need:

- Vite dev proxy config updated with `ws: true` for the `/ws/*` prefix.
- Litestar WebSocket handler must validate the `Origin` header explicitly
  (Litestar's `CORSConfig` does not apply to WebSocket upgrades).
- Production reverse proxy (nginx, Caddy) must be configured to proxy
  WebSocket upgrades to port 20001.

### 5.5 Dev-link vs production dependency mode

The `justfile` provides three recipes for switching between published and local
ai-accounts packages:

| Recipe | What it does |
|--------|-------------|
| `just dev-link-ai-accounts` | Builds TS packages in the local ai-accounts clone, then `npm install --no-save` (frontend) and `uv pip install -e` (backend) to use local code. Package.json/pyproject.toml stay pinned to published versions. |
| `just dev-unlink-ai-accounts` | Restores published versions via `npm install` and `uv sync --reinstall-package`. |
| `just dev-link-status` | Reports whether each package is using a local or published version. |

**Key detail:** `--no-save` means the frontend `package.json` always shows the
published version pin, even when running against local code. This is intentional
-- it prevents accidental commits of local-path dependencies.

**Override location:** Set `AI_ACCOUNTS_PATH=/abs/path` before the just command
if your ai-accounts clone is not at `../ai-accounts`.

---

## 6. Breaking Change Surface (Stable Contract at 0.3.0)

Everything below constitutes the public API frozen at 0.3.0. Changing any of
these requires a 0.4.0 release.

### 6.1 Python types (msgspec Structs)

**Domain:**
- `Backend` (fields: id, kind, display_name, config, status, created_at, updated_at, last_error)
- `BackendStatus` enum (UNCONFIGURED, DETECTING, NEEDS_LOGIN, VALIDATING, READY, ERROR)
- `BackendCredential` (fields: id, backend_id, ciphertext, key_id, created_at, expires_at)
- `DetectResult` (fields: installed, version, path, notes)
- `BackendKind` constants (CLAUDE, OPENCODE, GEMINI, CODEX)
- `OnboardingState` (fields: id, current_step, selected_backend_kind, created_backend_id, error)
- `OnboardingStep` enum (WELCOME, DETECT, PICK_BACKEND, LOGIN, VALIDATE, DONE)
- `LiveSession` (fields: id, kind, backend_id, state, started_at, last_seen_at)
- `SessionKind` enum (CHAT, PTY)
- `SessionState` enum (STARTING, ACTIVE, DISCONNECTED, ENDED, ERRORED)
- `ChatSession` (fields: id, backend_id, title, created_at, updated_at, model)
- `ChatMessage` (fields: id, session_id, role, content, created_at, model, tokens_in, tokens_out)
- `ChatRole` enum (SYSTEM, USER, ASSISTANT, TOOL)
- `Principal` (fields: id, display_name)

**Metadata:**
- `BackendMetadata` (fields: kind, display_name, icon_url, install_check, login_flows, plan_options, config_schema, supports_multi_account, isolation_env_var)
- `InstallCheck` (fields: command, version_regex)
- `InputSpec` (fields: name, label, kind, placeholder)
- `LoginFlowSpec` (fields: kind, display_name, description, requires_inputs)
- `PlanOption` (fields: id, label, description)

**Login events (discriminated union, tag field = "type"):**
- `UrlPrompt` (tag: "url_prompt", fields: prompt_id, url, user_code)
- `TextPrompt` (tag: "text_prompt", fields: prompt_id, prompt, hidden)
- `StdoutChunk` (tag: "stdout", fields: text)
- `ProgressUpdate` (tag: "progress", fields: label, percent)
- `LoginComplete` (tag: "complete", fields: account_id, backend_status)
- `LoginFailed` (tag: "failed", fields: code, message)
- `PromptAnswer` (fields: prompt_id, answer)

**Wire protocol (discriminated union, tag field = "type"):**
- `WIRE_PROTOCOL_VERSION = 1`
- `SessionStartEvent`, `SessionEndEvent`, `ChatTokenEvent`, `ChatToolCallEvent`, `ChatDoneEvent`, `PtyOutputEvent`, `PtyResizeEvent`, `PtyExitEvent`, `ErrorEvent`
- `WireEvent` union type
- `encode_wire_event()`, `decode_wire_event()` functions

**Service errors (exception classes with `code` attribute):**
- `ServiceError` (code: "service_error")
- `BackendNotFound` (code: "backend_not_found")
- `BackendAlreadyExists` (code: "backend_already_exists")
- `BackendKindUnknown` (code: "backend_kind_unknown")
- `BackendNotReady` (code: "backend_not_ready")
- `BackendValidationFailed` (code: "backend_validation_failed")
- `CredentialMissing` (code: "credential_missing")
- `LoginFlowUnsupported` (code: "login_flow_unsupported")

### 6.2 Python protocols (abstract interfaces)

- `BackendProtocol` -- kind, supported_login_flows, metadata, detect(), begin_login(), validate(), list_models(), chat(), pty()
- `LoginSession` ABC -- session_id, backend_kind, flow_kind, done, events(), respond(), cancel()
- `StorageProtocol` -- backends(), sessions(), history(), onboarding(), migrate(), close()
- `BackendRepository` -- create(), get(), list(), update(), delete(), put_credential(), get_credential(), delete_credential()
- `SessionRepository` -- upsert(), get(), list_active(), end()
- `HistoryRepository` -- create_session(), append_message(), list_messages(), list_sessions()
- `OnboardingRepository` -- get(), put()
- `VaultProtocol` -- encrypt(), decrypt(), current_key_id(), rotate()
- `AuthProtocol` -- authenticate()
- `TransportProtocol` -- send(), receive(), close()

### 6.3 HTTP routes

| Method | Path | Controller |
|--------|------|-----------|
| GET | `/health` | health() |
| GET | `/api/v1/backends/` | BackendsController.list_backends |
| POST | `/api/v1/backends/` | BackendsController.create_backend |
| GET | `/api/v1/backends/{id}` | BackendsController.get_backend |
| PATCH | `/api/v1/backends/{id}` | BackendsController.update_backend |
| DELETE | `/api/v1/backends/{id}` | BackendsController.delete_backend |
| POST | `/api/v1/backends/{id}/detect` | BackendsController.detect |
| POST | `/api/v1/backends/{id}/validate` | BackendsController.validate |
| GET | `/api/v1/backends/_meta` | MetaController.list_metadata |
| POST | `/api/v1/backends/{id}/login/begin` | LoginController.begin |
| GET | `/api/v1/backends/{id}/login/stream` | LoginController.stream (SSE) |
| POST | `/api/v1/backends/{id}/login/respond` | LoginController.respond |
| POST | `/api/v1/backends/{id}/login/cancel` | LoginController.cancel |
| POST | `/api/v1/backends/{kind}/install` | InstallController.install |
| GET | `/api/v1/cliproxy/status` | CliproxyController.status |
| POST | `/api/v1/cliproxy/install` | CliproxyController.install |
| POST | `/api/v1/cliproxy/login/begin` | CliproxyController.login_begin |
| POST | `/api/v1/cliproxy/login/callback-forward` | CliproxyController.login_callback_forward |
| POST | `/api/v1/onboarding/` | OnboardingController.start |
| GET | `/api/v1/onboarding/{id}` | OnboardingController.get_state |
| POST | `/api/v1/onboarding/{id}/detect` | OnboardingController.detect |
| POST | `/api/v1/onboarding/{id}/pick` | OnboardingController.pick |
| POST | `/api/v1/onboarding/{id}/login` | OnboardingController.begin_login |
| POST | `/api/v1/onboarding/{id}/finalize` | OnboardingController.finalize |

### 6.4 TypeScript types and events

**AiAccountsEvent (discriminated union, `type` field):**
- `wizard.opened`, `wizard.step`, `wizard.account.created`, `wizard.closed`
- `login.started`, `login.prompt`, `login.completed`, `login.failed`
- `internal.handler_error`

**AiAccountsClient public methods:**
- `listBackends()`, `createBackend()`, `getBackend()`, `deleteBackend()`, `updateBackend()`
- `detectBackend()`, `loginBackend()`, `pollBackendLogin()`, `validateBackend()`
- `beginLogin()`, `respondLogin()`, `cancelLogin()`, `streamLogin()`
- `getBackendMetadata()`
- `startOnboarding()`, `getOnboarding()`, `detectForOnboarding()`, `pickOnboardingKind()`
- `beginOnboardingLogin()`, `pollOnboardingLogin()`, `finalizeOnboarding()`
- `installBackendCli()`
- `cliproxyStatus()`, `cliproxyInstall()`, `cliproxyLoginBegin()`, `cliproxyCallbackForward()`

**WireEvent types (generated from Python, `@generated` header):**
- `SessionStartEvent`, `SessionEndEvent`, `ChatTokenEvent`, `ChatToolCallEvent`
- `ChatDoneEvent`, `PtyOutputEvent`, `PtyResizeEvent`, `PtyExitEvent`, `ErrorEvent`

---

## 7. Known Tech Debt

### 7.1 `NotImplementedError` stubs

All four backends + FakeBackend raise `NotImplementedError` for `chat()` and `pty()`:

| File | Line | Message |
|------|------|---------|
| `packages/core/src/ai_accounts_core/backends/claude.py` | 273 | "chat lands in Phase 3" |
| `packages/core/src/ai_accounts_core/backends/claude.py` | 282 | "pty lands in Phase 4" |
| `packages/core/src/ai_accounts_core/backends/opencode.py` | 258 | "chat lands in Phase 3" |
| `packages/core/src/ai_accounts_core/backends/opencode.py` | 267 | "pty lands in Phase 4" |
| `packages/core/src/ai_accounts_core/backends/gemini.py` | 457 | "chat lands in Phase 3" |
| `packages/core/src/ai_accounts_core/backends/gemini.py` | 466 | "pty lands in Phase 4" |
| `packages/core/src/ai_accounts_core/backends/codex.py` | 363 | "chat lands in Phase 3" |
| `packages/core/src/ai_accounts_core/backends/codex.py` | 372 | "pty lands in Phase 4" |
| `packages/core/src/ai_accounts_core/testing/fakes.py` | 284 | "chat lands in Phase 3" |
| `packages/core/src/ai_accounts_core/testing/fakes.py` | 287 | "pty lands in Phase 4" |

### 7.2 Vault key rotation not implemented

| File | Line | Context |
|------|------|---------|
| `packages/core/src/ai_accounts_core/adapters/vault_envkey/vault.py` | 86 | `raise NotImplementedError("EnvKeyVault rotation not supported in v0.1")` |

### 7.3 `pragma: no cover` exclusions

| File | Line | Context |
|------|------|---------|
| `packages/core/src/ai_accounts_core/login/cli_orchestrator.py` | 156 | `except Exception:  # pragma: no cover - child side` (post-fork child process error path) |
| `packages/core/src/ai_accounts_core/login/session.py` | 41 | `yield  # pragma: no cover  # makes the abstract body an async generator` |
| `packages/core/src/ai_accounts_core/backends/claude.py` | 106, 110, 121 | `except Exception:  # pragma: no cover - best-effort` (cleanup after orchestrator terminate/wait) |

### 7.4 `noqa` suppressions

| File | Line | Context |
|------|------|---------|
| `packages/core/src/ai_accounts_core/cliproxy/manager.py` | 107 | `except Exception as exc:  # noqa: BLE001` (broad exception in install loop) |

### 7.5 `xfail` markers

| File | Line | Context |
|------|------|---------|
| `backend/tests/integration/test_ai_accounts_proxy.py` | 112-120 | `@pytest.mark.xfail` on `test_onboarding_full_flow` -- the synchronous FakeBackend api_key path no longer satisfies the begin_login/stream/respond flow introduced in alpha.1. Needs rewrite against streaming login. |

### 7.6 Version string mismatch

| File | Line | Context |
|------|------|---------|
| `packages/core/src/ai_accounts_core/__init__.py` | 3 | `__version__ = "0.2.2"` -- stale, should be `"0.3.0a2"` to match `pyproject.toml`. The `/health` endpoint reports this stale version. |

### 7.7 Missing WAL mode

SQLite storage does not enable WAL mode. See section 5.3.

### 7.8 No periodic sweep of stale login sessions

`LoginSessionRegistry.sweep()` exists but is never called automatically. There
is no background task or periodic timer that invokes it. Stale sessions
accumulate in memory until the sidecar restarts.

### 7.9 Global mutable state in cliproxy routes

`packages/litestar/src/ai_accounts_litestar/routes/cliproxy.py` line 52:
```python
_ACTIVE_PROCS: dict[str, object] = {}
```
Module-level mutable dict tracking active cliproxy subprocess references.
Not cleaned up on sidecar shutdown. `asyncio.create_task(_reap())` at line 110
is fire-and-forget with no error handling on the task.

### 7.10 Hardcoded Google OAuth client ID

`packages/core/src/ai_accounts_core/backends/gemini.py` line 137:
```python
_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
```
This is the Gemini CLI's public client ID used for direct OAuth PKCE. It is not
a secret, but hardcoding it means a Gemini CLI update that changes the client ID
requires a code change and release.
