# Changelog

All notable changes to ai-accounts packages in this monorepo.

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
