# Changelog

All notable changes to ai-accounts packages in this monorepo.

## 0.3.1 — 2026-04-17

Security hardening, schema-migration root-cause fix, and cleanup of issues found by an automated code review pass.

### Security
- **Auth middleware now actually enforces `config.auth`** (`ai-accounts-litestar`). Previously the configured `AuthProtocol` provider was only *checked* at startup — no middleware was installed, so every endpoint was effectively unauthenticated even with `ApiKeyAuth` configured. The new `AuthMiddleware` wraps every request (exempting `/health` and `/schema`), calls `authenticate()`, returns 401 on `None` principal, and exposes the principal via `scope["state"]["principal"]`. Production guard also now refuses to start with `auth=None`.
- **Login sessions bound to `backend_id`** (`ai-accounts-core`, `ai-accounts-litestar`). `LoginSessionRegistry.register()` now requires a `backend_id=` kwarg; `get()` takes an optional `backend_id` verifier. All login routes (`/stream`, `/respond`, `/cancel`) pass the route's `backend_id` to the registry, closing three cross-backend attach / credential-misroute paths that a leaked `session_id` could have exploited. Mismatches look like not-found to prevent probing.
- **Login auto-store/validate failures now emit an explicit SSE error frame** instead of being swallowed — clients no longer see "login complete" while the backend is actually unusable.

### Fixed
- **Real versioned schema migrations** (`ai-accounts-core`). `SqliteStorage.migrate()` previously used `CREATE TABLE IF NOT EXISTS` only, which silently left pre-existing tables with out-of-date columns when new columns were added. Pre-0.3.0 databases lacked `rate_limited_until`, `rate_limit_reason`, `last_used_at`, and `last_polled_at` on `backends`, forcing downstream consumers (notably HypePaper) to hand-roll backfill logic. New `migrations.py` module adds a versioned `MIGRATIONS` list, idempotent `ALTER TABLE` statements with duplicate-column tolerance, and a `CURRENT_VERSION=2` baseline. Fresh DBs run the baseline schema and jump to current; pre-0.3.0 DBs walk the migration list and self-heal.
- **SSE framing bugs in the TypeScript clients** (`@ai-accounts/ts-core`). `chat-stream.ts` and `smart-chat-stream.ts` split event frames on `\n\n` only, dropped events on servers emitting CRLF, parsed each `data:` line independently (losing multi-line payloads), and never flushed the decoder + residual buffer on stream close. Unified into a single `parseSseFrames` helper in `sse-parser.ts` that handles CRLF/LF, multi-line `data:` joined with `\n`, EOF flush, and `response.body` null-guard.
- **`ChatStateService` concurrency and mutation hazards** (`ai-accounts-core`). Single process-wide `threading.Lock` replaced with per-session locks so unrelated sessions no longer serialize on each other. Events returned from `replay()` / `get_event_log()` are now deep-copied — callers mutating a returned dict can no longer corrupt the retained log. New `replay_with_gap()` returns `ReplayResult(events, gap)` so callers detect eviction instead of silently missing history; `chat_send.py` emits an explicit `{kind: "gap"}` SSE event to reconnecting clients when this happens.
- **`conversations.py` input validation + error translation** (`ai-accounts-litestar`). Added msgspec min/max length constraints on `backend_id`, `model`, `title`, and `content`. `KeyError` on unknown session now returns 404 instead of falling through to 500. The streaming endpoint preflights session existence before opening the SSE response and wraps in-stream errors into structured SSE error frames.
- **`useSmartScroll` lifecycle** (`@ai-accounts/vue-headless`). Listeners and the `MutationObserver` previously attached only to the element present at mount; swapping `containerRef` left stale listeners on the old node and auto-scroll silently broke. Now watches `containerRef` with `flush: 'post'` and reattaches on change. Also observes `characterData: true` so streaming-token text-node mutations trigger auto-scroll.

### Changed
- **`AccountService.create` now dedups on re-run** (`ai-accounts-core`). Re-running the "Add Account" flow for the same underlying credentials no longer creates duplicate backend rows. Match keys in priority order: `(kind, config_path)` for CLI-managed creds, `(kind, api_key_env)` for API-key flows, `(kind, email)` as a last resort. When a match exists, `display_name` and `config` are merged into the existing row instead of spawning a duplicate.

### Developer experience
- Migrated auth middleware from deprecated `AbstractMiddleware` to `ASGIMiddleware` (litestar 2.15+), eliminating the deprecation warning.

---

## 0.3.0 — 2026-04-16

Stable release consolidating all alpha work: multi-backend login, smart chat, PTY sessions, and security hardening.

See alpha entries below for detailed per-feature changelogs.

### Fixed (since alpha.3)
- SSE reconnect seq-seed bug — post-eviction reconnects now produce monotonic seq IDs
- 5 silent `catch` blocks in `useStreamingParser` now log with context
- Heartbeat timeout now aborts in-flight fetch via AbortController
- Compound synthesis no longer silently falls back to `"claude"` on error
- `pty.fork()` → `os.forkpty()` for Python 3.14 compatibility

### Changed (since alpha.3)
- Heartbeat tuning: server 30s→20s, client 65s→90s
- `sendChat()` now accepts `{ signal, lastEventId }` options

---

## 0.3.0-alpha.3 — 2026-04-15

Smart AI chat panel v2 — real-time tool call visibility, resilient streaming, and message actions on top of the alpha.2 chat foundation.

### Added
- `ToolCallEvent` domain type (`ai-accounts-core`) — emitted by `ChatOrchestrator` when backends invoke tools
- `ChatStateService` (`ai-accounts-core`) — per-session seq numbering, event replay, and SSE reconnection support
- `tool_call` event streaming on `POST /api/v1/chat/send` SSE (`ai-accounts-litestar`)
- `@ai-accounts/ts-core`: `tool_call` variant on `SmartChatEvent` + `ProcessGroup` types
- `@ai-accounts/vue-headless`:
  - `useProcessGroups` composable — groups sequential tool calls into collapsible process groups
  - `useStreamingParser` composable — incremental markdown parsing via `streaming-markdown` (smd.js)
  - `useSmartChat`: seq-based event deduplication, heartbeat watchdog, finalization state
- `@ai-accounts/vue-styled`:
  - `ProcessGroup` component (tool-type badges + collapse)
  - `MessageActions` component (copy, retry, edit) wired into `ChatBubble`
  - `FinalizationBanner` component
  - `AiChatPanel` integration with density-aware defaults

### Fixed
- `tool_call` dispatch and `MessageActions` prop typing
- `vue-headless` dependency name — was typo `smd`, corrected to `streaming-markdown`

## 0.3.0-alpha.2 — 2026-04-11

### Fixed
- **`_ClaudeCliBrowserSession` stuck at "Starting login session..."** — port of `claude /login` did not handle Claude Code's interactive first-run TUI (theme picker, menu prompts, REPL idle detection). Ported Agented's interactive loop: emits a `ProgressUpdate` immediately, detects numbered menu options (`❯ 1. Dark mode`) and emits as `TextPrompt`, navigates via arrow keys on respond, detects REPL idle + re-sends `/login`, parses the OAuth URL. Shared impl in `ai_accounts_core/login/interactive.py`. End-to-end verified against real `claude 2.1.101`.
- **`AccountWizard` account name was required** — `subscriptionValid` gated `goNext` on non-empty name. Now genuinely optional; falls back to backend metadata `display_name` at save time. Label changed from "Name *" to "Name (optional)".

### Added
- `CliOrchestrator.poll_output()` — timeout-based output polling for interactive loops
- `parse_menu_options`, `send_menu_selection`, `MenuOption` helpers
- `run_interactive_cli_login()` shared state machine in `login/interactive.py`
- `_NUMBERED_OPTION_RE`, `_LOGIN_SUCCESS_RE`, `_URL_IN_OUTPUT_RE` module-level patterns

#### PTY Session System (originally planned as alpha.4)
- `AsyncPtyHandle` — async PTY subprocess wrapper with read/write/resize (`ai_accounts_core/pty/handle.py`)
- `PtyService` — session lifecycle management: spawn/attach/kill backed by `SessionRepository`
- `BackendProtocol.pty()` — implementations for Claude, Codex, Gemini, OpenCode backends
- `FakeBackend.pty()` + `AsyncPtyHandle`-based fake for test fixtures
- Litestar: `POST /api/v1/pty/spawn`, `/kill`, `/resize` + WebSocket `/ws/pty/{session_id}` binary frame bridge
- `@ai-accounts/ts-core`: `PtySocket` reconnect-capable WebSocket client + `spawnPty()`, `killPty()`, `resizePty()` methods
- `@ai-accounts/vue-headless`: `usePtySession` composable with reactive state
- `@ai-accounts/vue-styled`: `TerminalView.vue` component with xterm.js integration
- `xterm` + `@xterm/addon-fit` dependencies added to `vue-styled`

#### Security Hardening (originally planned as alpha.5)
- Fix SSRF port bypass in `cliproxy/manager.py` — validate port in allowed range, not just host
- Fix fd leak in `backends/claude.py` cleanup paths — narrow `except` catches to `(OSError, ProcessLookupError)` + log
- Replace silent key-format leak in error messages
- Narrow `finally`-block catches across backends; log previously-swallowed errors
- Log `rmtree` failures during account deletion instead of silently ignoring
- Add `GET /api/v1/backends/{id}/models` route + `list_models()` wiring across backends
- PR review fixes: typed DTOs, 204-no-content for empty pick responses, kind-filter fallback, timeout double-wrap removal, `backend_id` keying, structured logging, port validation, stderr capture
- Enable SQLite WAL mode for concurrent read performance
- Path traversal hardening via `Path.is_relative_to()` checks

### Test coverage
- 14 new unit tests for menu parsing + regexes + diff-line false-positive regression
- Rewritten Claude cli_browser login test with faked `time.monotonic` for deterministic timing
- 5 `AsyncPtyHandle` + `PtyService` tests (spawn/attach/kill roundtrip)
- 2 Litestar PTY REST route tests (spawn/kill)
- 5 `cliproxy/manager` unit tests
- 6 direct `run_interactive_cli_login` state-machine tests
- 3 real-subprocess `CliOrchestrator` tests (echo + cat + claude --version)

### Fixed (Python 3.14 compatibility)
- `cli_orchestrator.py` — replace removed `pty.fork()` with `os.forkpty()` (Python 3.14+)
- `test_strip_ansi_cursor_positioning` — align test with intentional semantics where cursor-row reposition (`ESC[H`) yields `\n` and column-only movement yields space

## 0.3.0-alpha.1 — 2026-04-11

### Added
- `LoginSession` ABC + `LoginEvent` discriminated union + `LoginSessionRegistry` — central abstraction for interactive backend login flows (`ai-accounts-core`)
- `CliOrchestrator` — PTY-based subprocess runner ported from Agented, supports stdout streaming, stdin writes, graceful terminate (`ai-accounts-core`)
- `BackendMetadata` + `BackendRegistry` served at `GET /api/v1/backends/_meta` — Python-side source of truth for backend capabilities, login flows, install commands, config schema
- `POST /api/v1/backends/{id}/login/begin` + SSE `GET /login/stream` + `/respond` + `/cancel` — interactive login route family (`ai-accounts-litestar`)
- `POST /api/v1/backends/{kind}/install` — per-backend CLI auto-installer
- `POST /api/v1/cliproxy/install` + `/cliproxy/status` + `/cliproxy/login/begin` + `/cliproxy/login/callback-forward` — CLIProxyAPI install and account registration
- `ClaudeBackend`, `CodexBackend`, `GeminiBackend`, `OpenCodeBackend` — real login flows:
  - Claude: `cli_browser` + `api_key`
  - Codex: `oauth_device` + `cli_browser` + `api_key`
  - Gemini: `oauth_device` + `direct_oauth` (PKCE) + `api_key`
  - OpenCode: `cli_browser` + `api_key`
- `AiAccountsClient` new methods: `beginLogin`, `streamLogin` (SSE consumer), `respondLogin`, `cancelLogin`, `getBackendMetadata`, `installBackendCli`, `cliproxyStatus`, `cliproxyInstall`, `cliproxyLoginBegin`, `cliproxyCallbackForward` (`@ai-accounts/ts-core`)
- `AiAccountsEvent` typed discriminated union (wizard + login lifecycle events) + event bus through `aiAccountsPlugin` (`@ai-accounts/vue-headless`)
- `aiAccountsPlugin`, `useAiAccounts`, `useBackendRegistry`, `useLoginSession` composables (`@ai-accounts/vue-headless`)
- `AccountWizard` (ported from Agented's polished 1947-line wizard), `BackendPicker`, `LoginStream`, `AccountEditForm` (`@ai-accounts/vue-styled`)

### Breaking
- `BackendProtocol.login()` / `poll_login()` removed. Backends now implement `begin_login(flow_kind, config, vault_ctx, isolation_dir) -> LoginSession`. Clean break from 0.2.x.
- `AccountService.login()` / `poll_login()` removed. Use `AccountService.begin_login(account_id, flow_kind, inputs) -> LoginSession`.
- Legacy `LoginResponseDTO` / `OAuthDeviceLoginDTO` / `LoginRequest` / `PollLoginRequest` removed from `ai-accounts-litestar`.
- Legacy `/api/v1/backends/{id}/login` and `/login/poll` routes removed. Use new SSE-based `/login/begin`, `/login/stream`, `/login/respond`, `/login/cancel`.

### Deprecated
- All 0.2.x releases — upgrade to 0.3.0-alpha.1.

### Migration
- Host apps: install `aiAccountsPlugin` at app root with `{client, onEvent?}`. Use `<AccountWizard>` from `@ai-accounts/vue-styled`. Old `backendApi` shim pattern no longer needed.
- Python host apps: construct `AiAccountsConfig(..., login_session_ttl_seconds=600.0)` and pass to `create_app`. Backends must provide `metadata: ClassVar[BackendMetadata]` and `begin_login()`.

### Notes
- Chat panel, PTY session management, and conversation store are deferred to `0.3.0-alpha.2` and `0.3.0-alpha.3`.

## 0.2.0 — 2026-04-11

### Added

- `OnboardingService` state machine (welcome → detect → pick → login → done), persisted via `OnboardingRepository`
- `GeminiBackend` with API-key and OAuth device flow (driven via `gemini auth login` CLI subprocess)
- `CodexBackend` with API-key and OAuth device flow (driven via `codex auth login` CLI subprocess)
- `<OnboardingFlow>` Vue component with tabbed API-key vs OAuth login, verification URL + copy-code UI, auto-polling
- `useOnboarding` Vue composable
- `createOnboardingFlow` TypeScript state machine in `ts-core`
- `POST /api/v1/onboarding/*` HTTP routes
- `POST /api/v1/backends/{id}/login/poll` HTTP route for OAuth polling
- Per-account isolation directories under `AiAccountsConfig.backend_dirs_path` (default `./backend_dirs`)
- `BackendProtocol.supported_login_flows: ClassVar[frozenset[str]]`

### Changed (BREAKING)

- `BackendProtocol.login()` returns `LoginResult` (tagged union) instead of `bytes`
- `BackendProtocol.login/validate/list_models/chat/pty` all take a new `isolation_dir: Path` kwarg
- `BackendProtocol.poll_login(handle, isolation_dir)` added
- `AccountService.__init__` requires `isolation_base_dir: Path`
- `AccountService.login()` returns `LoginResponse` (kind=complete|pending) instead of `Backend`
- `AccountService.delete()` cascades to the isolation directory (`shutil.rmtree`)
- `AiAccountsClient.loginBackend()` TypeScript return type changes from `unknown` to `LoginResponseDTO`
- `AiAccountsConfig` gains `backend_dirs_path: Path`

### Migration guide

If you are a third-party author of a `BackendProtocol` implementation:

1. Add `supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})` to your class
2. Change method signatures to accept `isolation_dir: Path` as a keyword-only argument
3. Change `login()` to return `CredentialLogin(credential=...)` for API-key flows instead of returning bytes directly. Return `LoginError(code, message)` on validation failures — don't raise
4. Implement `poll_login(handle, isolation_dir)`. For backends that only support synchronous flows, return `LoginError(code="not_pollable", ...)`
5. Use `isolation_dir` to isolate per-account CLI state. Set the appropriate env var (`CLAUDE_CONFIG_DIR`, `GEMINI_CLI_HOME`, `CODEX_HOME`, etc.) when invoking the CLI

## 0.1.0 — 2026-04-11

Initial release. See Phase 0+1 plan for feature list.
