# @ai-accounts/ts-core

## 0.3.12

### Patch Changes

- `client.discoverConfigs()` and `client.importDiscovered({kind, path, display_name})` wrap the new `GET /api/v1/discovery/` and `POST /api/v1/discovery/import` routes. `discoverConfigs` returns globbed CLI candidates with `is_logged_in`, `suggested_name`, and `backend_id` (set when the path is already imported — server has synced its status to the probe result).
- Chat-stream error frame decoding now handles gzipped proxy error bodies — was leaking compressed bytes into the UI.

## 0.3.11

### Patch Changes

- No public API additions; published alongside the gemini subscription flow + wizard method picker in `vue-styled`.

## 0.3.10

### Patch Changes

- New `LoginEvent` types are surfaced via the SSE login stream — `write_eager`, intermediate prompt acks, and verifying-state markers consumed by `vue-headless`/`vue-styled`.

## 0.3.9

### Patch Changes

- Add `BackendAccountOption` type and change `BackendOption.accounts` from `string[]` to `Array<{id, label}>` so account dropdowns can show display_name/email while still emitting the backend id.
- Add `AiAccountsClient.listModels(backendId)` wrapping `GET /api/v1/backends/{id}/models`.
- Add `AiAccountsClient.cliproxyLoginStatus(sessionId)` and `CliproxyLoginStatus` type for polling cliproxy login completion (device-code flow).
- `CliproxyLoginBeginResponse` now carries `session_id` for the new polling endpoint.
- `SmartChatEvent` `backend_*` variants gained `backend_kind` + `account_label` fields so the chat panel can render "Claude · user@example.com" instead of an opaque `bkd-…` hash.

> Versions 0.2.3 through 0.3.8 backfilled from git log on 2026-05-04 — entries below.

## 0.3.8

### Patch Changes

- No changes specific to ts-core; published as part of monorepo bump alongside Claude v1 REPL login fix and OAuth error detection.

## 0.3.7

### Patch Changes

- `client.writeEagerLogin(accountId, sessionId, text)` for the new direct-PTY-write path that bypasses the prompt-detection regex (Claude CLI v2 occasionally never emits "Paste code here").

## 0.3.6

### Patch Changes

- No changes specific to ts-core; LoginStream eager paste-code form is shipped from vue-styled.

## 0.3.5

### Patch Changes

- **Fix**: `parseSseLoginEvents` normalises CRLF → LF (Litestar emits `\r\n\r\n` frames; the LF-only matcher was silently yielding nothing and the wizard hung). New regression tests cover both CRLF and LF separators.

## 0.3.4

### Patch Changes

- No client changes; bumped alongside the core regex fix for `https://claude.com/*` OAuth URLs.

## 0.3.3

### Patch Changes

- No new public API; published alongside SSE replay + wizard polish in core/vue-styled.

## 0.3.0 — 0.3.2

### Minor / Patch Changes

The 0.3.0-alpha sequence and 0.3.2 stable rolled into ts-core in one block:
- Smart-chat types, SSE parser, and `sendChat` client method.
- Scheduler types and client methods.
- CLIProxy server lifecycle client methods (`start`, `stop`, `status`).
- `config_dir` exposed in backend API responses.
- Auth middleware bound login sessions to backend_id.
- Static binary rebuild after pre-1.0 type churn.

See root `CHANGELOG.md` `## 0.3.2` and `## 0.3.1` entries for the full feature
and security narrative.

## 0.2.2

### Patch Changes

- Fix AiAccountsClient constructor binding global `fetch` to the instance, which triggered "Illegal invocation" in browsers. Now wraps the default fetch so it's called against the global scope. Caller-supplied fetch is passed through unchanged.

## 0.2.1

### Patch Changes

- Add PATCH /api/v1/backends/{id} route, AccountService.update(), and AiAccountsClient.updateBackend() for editing backend display_name and config after creation.

## 0.2.0

### Minor Changes

- Add OnboardingFlow, Gemini + Codex backends with OAuth device flow, and per-account isolation directories.

  BREAKING: BackendProtocol.login() now returns LoginResult (tagged union of CredentialLogin, OAuthDeviceLogin, LoginError) and takes isolation_dir: Path. All validate/list_models/chat/pty methods also require isolation_dir. New poll_login() method. AccountService constructor now requires isolation_base_dir. AiAccountsClient.loginBackend() TypeScript return type changes from unknown to LoginResponseDTO.

## 0.1.0

### Minor Changes

- First public preview: account management, Claude + OpenCode backends, themeable Vue wizard.

  Adds:

  - `ai-accounts-core` Python package with Protocol-based architecture (Storage, Vault, Auth, Backend, Transport)
  - `ai-accounts-litestar` HTTP layer with /api/v1/backends routes and production-mode startup guard
  - `@ai-accounts/ts-core` TypeScript client (AiAccountsClient, accountWizard state machine)
  - `@ai-accounts/vue-headless` Vue 3 composable (useAccountWizard)
  - `@ai-accounts/vue-styled` Vue 3 AccountWizard component with CSS custom property theming
