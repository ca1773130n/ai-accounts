# @ai-accounts/ts-core

## 0.3.9

### Patch Changes

- Add `BackendAccountOption` type and change `BackendOption.accounts` from `string[]` to `Array<{id, label}>` so account dropdowns can show display_name/email while still emitting the backend id.
- Add `AiAccountsClient.listModels(backendId)` wrapping `GET /api/v1/backends/{id}/models`.
- Add `AiAccountsClient.cliproxyLoginStatus(sessionId)` and `CliproxyLoginStatus` type for polling cliproxy login completion (device-code flow).
- `CliproxyLoginBeginResponse` now carries `session_id` for the new polling endpoint.
- `SmartChatEvent` `backend_*` variants gained `backend_kind` + `account_label` fields so the chat panel can render "Claude · user@example.com" instead of an opaque `bkd-…` hash.

> Versions 0.2.3 through 0.3.8 ship on npm but were not entered here in real time (changesets-flow gap). Recoverable from git log between the corresponding tags. See the root `CHANGELOG.md` for the 0.3.9 monorepo summary.

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
