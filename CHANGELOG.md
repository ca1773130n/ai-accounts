# Changelog

All notable changes to ai-accounts packages in this monorepo.

## 0.3.9 — 2026-05-03

End-to-end fixes for the playground webui — codex device-code login, claude credential validation on macOS, multi-backend chat routing, and a polished playground app. Versions 0.3.3 through 0.3.8 ship on npm but were not entered here in real time; entries skipped (recoverable from `git log` between the corresponding tags).

### Added

- **Playground chat panel** (`apps/playground`) — `<AiChatPanel density="detailed">` mounted below the accounts list. Selects a ready backend automatically, lazy-loads its model list from `GET /api/v1/backends/{id}/models`, defaults `selectedModel` to the first available so the first send doesn't post `model=""`, and resets the session when the user switches backend or account (the server-side session is bound to its original `backend_id` — without reset, messages route through the old binding regardless of dropdown state).
- **Remove account** (`apps/playground`) — per-row Remove button with confirm dialog → `DELETE /api/v1/backends/{id}` → list refresh. Files under the backend's config directory are NOT deleted (documented in the confirm dialog).
- **Cliproxy device-code login flow for Codex** (`ai-accounts-core`, `cliproxy/manager.py`). `start_cliproxy_login("codex")` now spawns `cliproxyapi --codex-device-login` (was `--codex-login`). The browser-callback flow can't complete when the playground is reached over a remote URL — the OAuth provider redirects to localhost on the *user's* machine, not the playground host. Device-code emits a URL+code that works anywhere.
- **Cliproxy login completion polling** (`ai-accounts-litestar`, `routes/cliproxy.py`; `@ai-accounts/ts-core`; `@ai-accounts/vue-styled`). `POST /api/v1/cliproxy/login/begin` now returns a `session_id`, and `GET /api/v1/cliproxy/login/status?session_id=…` exposes the spawned cliproxyapi process's terminal state (`running`/`completed`/`failed`/`timeout`). The `_reap()` task drains stdout (so cliproxyapi can't block on a full pipe) and records the final state. `AccountWizard` polls every 2s after device-code is emitted and auto-advances on completion. The misleading "paste callback URL" UI is hidden in device-code mode and replaced with a "Waiting for you to enter the code…" indicator.
- **`backend_kind` + `account_label` on fan-out events** (`ai-accounts-core`, `domain/chat_events.py`, `services/chat_orchestrator.py`). `AllModeEvent` and `CompoundEvent` now carry the backend's kind and a friendly display name alongside the `bkd-…` id, so the Smart Chat panel cards can render "Claude · spatiotemporal.traveler@gmail.com" with the correct color instead of an opaque hash.
- **`BackendAccountOption` type** (`@ai-accounts/ts-core`). `BackendOption.accounts` is now `Array<{id, label}>` (was `string[]`) so the Account dropdown shows the email/display_name while emitting the backend id as `account_id`. The previously read-only Account `<select>` in `ChatControls` is now wired to `selectedAccount` + `update:selectedAccount`.
- **`useSmartChat.resetSession()`** (`@ai-accounts/vue-headless`) drops `sessionId` + visible chat state so consumers can start a fresh conversation when the user switches backend.
- **`AiAccountsClient.listModels(backendId)`** (`@ai-accounts/ts-core`) wraps `GET /api/v1/backends/{id}/models` for callers that need to populate model dropdowns per backend.
- **`AiAccountsClient.cliproxyLoginStatus(sessionId)`** for the new login-completion polling endpoint.

### Fixed

- **Codex device code length truncated** (`ai-accounts-core`, `cliproxy/manager.py`). `_DEVICE_CODE_RE` was `[A-Z0-9]{4}-?[A-Z0-9]{4}` and silently captured only the first 8 alphanumeric characters of the cliproxy 4-5 codex format (e.g. captured `FXEJ-GY37` from `FXEJ-GY37O`). The wizard showed an 8-char code while the OpenAI device page expected 9 — login always failed. Second group widened to `{4,8}`; greedy matching captures the full code while still working for Claude's 4-4 format.
- **Cliproxy `auth-dir` mismatch** (`ai-accounts-core`, `cliproxy/manager.py`). `write_cliproxy_config` created an empty `~/.cli-proxy-api/auth/` subdir and pointed `auth-dir` at it. But cliproxyapi's own login subcommands write credential files (`codex-…json`, `claude-…json`, `gemini-…json`) into the config directory itself — the server scanned an empty subdir, registered zero providers, and rejected every chat with `unknown provider for model X`. `auth-dir` now points at the config directory.
- **Claude validate broken on macOS** (`ai-accounts-core`, `backends/claude.py`). Claude CLI on macOS stores credentials in the system Keychain (service `Claude Safe Storage`, account `Claude Key`), NOT in `<isolation>/.credentials.json`. The file-probe `validate()` from 0.3.7 silently returned False on every macOS login → freshly-logged-in backends stuck in `error`. `validate()` now runs `security find-generic-password` first on darwin and accepts a 0 exit as success; falls back to the file probe for other platforms / unusual setups. **Known limitation, documented inline:** macOS Keychain entries are not scoped by `CLAUDE_CONFIG_DIR`, so multiple "isolated" claude accounts on darwin share one credential — a second login swaps out the first.
- **Static model lists out of sync with cliproxyapi** (`ai-accounts-core`). `claude.list_models()` advertised `claude-opus-4-7` first, but cliproxyapi 6.8.30 has no provider mapping for it → 502 `unknown provider for model claude-opus-4-7`. Replaced with the 10 claude models cliproxyapi 6.8.30 advertises (`claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, etc.). `codex.list_models()` was shelling out to `codex models list --json` — the subcommand doesn't exist in codex 0.128.0 (same drift class as the earlier claude/gemini fixes), so the call always returned `[]`. Replaced with the 10 codex-flavored models cliproxyapi advertises (`gpt-5-codex`, `gpt-5.3-codex`, etc.).
- **Streaming responses rendered as "undefinedundefined…"** (`ai-accounts-litestar`, `routes/chat_send.py`). `ChatDelta` carries token text in `text`, but the frontend's `useSmartChat.dispatch` types `'token'` events as `{kind: 'token'; payload: string}` and reads `event.payload`. The route now copies `text → payload` at the SSE boundary for `kind in {token, error}`; All/Compound events (which already used `text`) are untouched.
- **Compound mode 401/429 from gemini provider** (`ai-accounts-core`, `services/chat_orchestrator.py`). `send_all`/`send_compound` passed `model="auto"` to each backend. cliproxyapi has no `"auto"` provider mapping, so it fell through to a default — apparently the gemini provider — and returned Google-style 401 (invalid OAuth) and 429 (RESOURCE_EXHAUSTED) from stale gemini credentials in cliproxyapi's auth dir. The orchestrator now resolves the backend's first advertised model via `list_models()` before each request; same fix applied to the synthesis call.
- **Missing CSS tokens collapsed wizard borders** (`@ai-accounts/vue-styled`, `styles/tokens.css`). The `AccountWizard` and `LoginStream` components were authored against an unprefixed token vocabulary (`--text-primary`, `--border-default`, `--accent-cyan`, …) but the library only shipped `--aia-*`-prefixed tokens. 19 tokens were undefined; 11 of them had no `var(…, fallback)` either, so rules like `border: 1px solid var(--border-default)` silently became invalid → rounded box borders, panel backgrounds, and accent chips collapsed in the popup. Added 19 component-side aliases mapping onto the existing `--aia-*` palette; consumers can override any of them in their own `:root`.
- **Chat panel posted `model=""` after backend switch** (`@ai-accounts/vue-styled`, `AiChatPanel.vue`). `selectBackend()` clears `selectedModel`. `handleSend` now lazy-loads models for the picked backend and defaults `selectedModel` to the first available before `createSession()` (was `400 "Expected str of length >= 1 at .model"`).

### Changed

- **Playground UI rewrite** (`apps/playground/src/App.vue`) — wider 960px container with proper vertical rhythm, card-style sections, per-kind colored left rail on account rows (claude/codex/gemini/opencode), pill status badges with colored dot + glow on `ready`, ellipsis-clamped names, monospace metadata chips, modal backdrop blur + click-outside-to-close, responsive breakpoint at 640px. Primary "Add account" CTA moved to the header instead of buried inside a section.

### Documentation

- This entry. Acknowledges the unfilled gap from 0.3.3 to 0.3.8 — contents of those versions are recoverable from `git log` between the corresponding tags. Per-package `CHANGELOG.md` files similarly skip from `0.2.2` to `0.3.9`; backfilling those is tracked separately.

---

## 0.3.2 — 2026-04-17

Stable release rolling up all 0.3.2-alpha.1 work plus post-release audit closures.

### Added
- **Claude v2 auth** (`ai-accounts-core`, `ClaudeBackend`) — `begin_login("cli_browser")` now uses `claude auth login --claudeai --email <email>` when an `email` is configured, falling back to the v1 interactive `/login` flow otherwise. v2 uses the public `platform.claude.com/oauth/code/callback` redirect (no localhost binding), so it works on remote boxes without a paste-callback workaround. `--email` also pre-fills Google's account picker. `ClaudeBackend.metadata` advertises `email` as an optional input on the `cli_browser` flow.
- **Codex OAuth URL detection** (`ai-accounts-core`, `CodexBackend`) — `_CODEX_URL_RE` now matches both `chatgpt.com/auth/*` and `auth.openai.com/*`, so the interactive-login state machine emits `UrlPrompt` immediately for either host.
- **PTY child orphan protection** (`ai-accounts-core`) — `PR_SET_PDEATHSIG` now set in both `cli_orchestrator.os.forkpty()` and `pty/handle.os.fork()` child branches. Linux-only via `prctl`; macOS silently no-ops (accepted platform limitation). Closes **RISKS-AND-BUGS H-5**.

### Fixed
- **Gemini OAuth: `client_secret` + peek-don't-pop PKCE state** (`ai-accounts-core`). The token-exchange POST to `oauth2.googleapis.com` now includes `client_secret` (required by Google for the web-client credential type Gemini CLI uses — publicly embedded in Gemini CLI, treated as a configuration constant). `_GeminiDirectOAuthSession.events()` now retries on token-exchange failure up to 3 times, keeping the PKCE `code_verifier`/`state` alive across attempts — so a transient Google 5xx or a typo in the auth code no longer wipes PKCE state and forces a hard re-login.
- **IPv6 callback** (`ai-accounts-core`, `forward_cliproxy_callback`) — now tries `[::1]` first, then `127.0.0.1`, then `localhost`. Claude CLI v2.1.92+ binds the local callback server to IPv6 loopback on macOS with IPv6-first stacks; cliproxyapi still listens on IPv4. Trying IPv6 first and falling back preserves both paths.
- **Claude URL capture hardening** — URL regex now matches `platform.claude.com` alongside `claude.ai` / `console.anthropic.com`, so the interactive login picks up v2 OAuth URLs.
- **`AccountService.delete`: `rmtree` failures logged** (`ai-accounts-core`) — `shutil.rmtree(isolation_dir, ignore_errors=True)` replaced with a `try/except OSError` that logs a warning, so stale credential directories can no longer accumulate invisibly on permission/filesystem issues. Closes **SILENT-FAILURES H-04**.
- **`_ACTIVE_PROCS` keyed on UUID** (`ai-accounts-litestar`, `routes/cliproxy.py`) — replaced `str(id(proc))` with `uuid.uuid4().hex`. Python object-id reuse after GC can no longer overwrite a live reaper entry. Closes **RISKS-AND-BUGS L-2**.
- **cliproxy fake-browser temp dir cleanup on every exit path** (`ai-accounts-core`, `cliproxy/manager.py`) — `CliproxyLoginInfo` carries a new `fake_dir` field; the three previously-leaky error paths in `start_cliproxy_login` and the reaper `finally` in `routes/cliproxy.py` all clean it up. Extends **SILENT H-04 / M-10** closure.

### Removed
- Stale `feat/0.3.0-alpha.1`, `feat/0.3.0-alpha.2-4`, `feat/smart-chat-panel`, `feat/usage-scheduler`, `fix/claude-login-config-and-menu-ui` branches pruned on origin. No code impact; housekeeping only.

### Documentation
- `docs/superpowers/MAINTENANCE.md` refreshed to 0.3.x reality — version refs updated, obsolete "chat() / pty() raise NotImplementedError" tech-debt section removed (those shipped in 0.3.0-alpha.2/4), proper release history table, and two new operator-facing sections for the **0.3.1 auth middleware** (5.6) and **schema-migration system** (5.7).
- `docs/superpowers/RISKS-AND-BUGS.md` and `SILENT-FAILURES.md` gained "Status at 0.3.1" blocks with per-item FIXED / PARTIAL / OPEN annotations grounded in real file:line refs. 13 RISKS items now closed (up from 11 in 0.3.1); C-5 reclassified as architectural tradeoff tracked for 0.4.0; H-07 reclassified as accepted top-level-handler design.
- New plan file: `docs/superpowers/plans/2026-04-17-ai-accounts-0.3.2-alpha.1.md` documents the Agented-parity motivation, per-commit scope, and release checklist.

---

## 0.3.2-alpha.1 — 2026-04-17

Prerelease. Superseded by 0.3.2 stable above — see that entry for the full scope.

---

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
