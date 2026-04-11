# Changelog

All notable changes to ai-accounts packages in this monorepo.

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
