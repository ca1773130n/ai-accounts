# @ai-accounts/vue-styled

## 0.3.9

### Patch Changes

- **`AiChatPanel`** — lazy-loads models per backend via `client.listModels()` and auto-defaults `selectedModel` to the first available before `createSession`. Without this, switching backend in the dropdown posted `model=""` and got 400 from the server. Account dropdown now passes `selectedAccount` through to `useSmartChat`. `pickBackendFor(kind, accountId)`: when an account is explicitly picked, uses that exact backend id instead of the kind's first ready. `watch(selectedBackend, selectedAccount)` calls `chat.resetSession()` so the next message creates a fresh server-side session bound to the new backend.
- **`ChatControls`** — Account `<select>` now has `value`/`change` wiring (was read-only by accident); options render `acc.label` and emit `acc.id`.
- **`AllModeResponses`** — card titles now key on `backendKind` (color + label like "Claude") plus a small muted `accountLabel` chip, instead of an opaque `bkd-…` hash.
- **`AccountWizard`** — polls `GET /api/v1/cliproxy/login/status?session_id=…` once a device-code session is started, so the wizard auto-advances when cliproxyapi exits cleanly. Hides the misleading "paste callback URL" section in device-code mode (no callback ever arrives) and replaces it with a "Waiting for you to enter the code…" indicator.
- **`tokens.css`** — added 19 component-side aliases (`text-primary`, `border-default`, `accent-cyan`, …) that the wizard / login-stream were authored against. Without these, properties like `border: 1px solid var(--border-default)` resolved to invalid → rounded box borders, panel backgrounds, and accent chips collapsed in the popup. Each maps onto an existing `--aia-*` token; consumers can override via their own `:root`.
- Updated dependencies
  - @ai-accounts/ts-core@0.3.9
  - @ai-accounts/vue-headless@0.3.9

> Versions 0.2.3 through 0.3.8 ship on npm but were not entered here in real time (changesets-flow gap). Recoverable from git log between the corresponding tags. See the root `CHANGELOG.md` for the 0.3.9 monorepo summary.

## 0.2.2

### Patch Changes

- Fix AiAccountsClient constructor binding global `fetch` to the instance, which triggered "Illegal invocation" in browsers. Now wraps the default fetch so it's called against the global scope. Caller-supplied fetch is passed through unchanged.
- Updated dependencies
  - @ai-accounts/ts-core@0.2.2
  - @ai-accounts/vue-headless@0.2.2

## 0.2.1

### Patch Changes

- Add PATCH /api/v1/backends/{id} route, AccountService.update(), and AiAccountsClient.updateBackend() for editing backend display_name and config after creation.
- Updated dependencies
  - @ai-accounts/ts-core@0.2.1
  - @ai-accounts/vue-headless@0.2.1

## 0.2.0

### Minor Changes

- Add OnboardingFlow, Gemini + Codex backends with OAuth device flow, and per-account isolation directories.

  BREAKING: BackendProtocol.login() now returns LoginResult (tagged union of CredentialLogin, OAuthDeviceLogin, LoginError) and takes isolation_dir: Path. All validate/list_models/chat/pty methods also require isolation_dir. New poll_login() method. AccountService constructor now requires isolation_base_dir. AiAccountsClient.loginBackend() TypeScript return type changes from unknown to LoginResponseDTO.

### Patch Changes

- Updated dependencies
  - @ai-accounts/ts-core@0.2.0
  - @ai-accounts/vue-headless@0.2.0

## 0.1.0

### Minor Changes

- First public preview: account management, Claude + OpenCode backends, themeable Vue wizard.

  Adds:

  - `ai-accounts-core` Python package with Protocol-based architecture (Storage, Vault, Auth, Backend, Transport)
  - `ai-accounts-litestar` HTTP layer with /api/v1/backends routes and production-mode startup guard
  - `@ai-accounts/ts-core` TypeScript client (AiAccountsClient, accountWizard state machine)
  - `@ai-accounts/vue-headless` Vue 3 composable (useAccountWizard)
  - `@ai-accounts/vue-styled` Vue 3 AccountWizard component with CSS custom property theming

### Patch Changes

- Updated dependencies
  - @ai-accounts/ts-core@0.1.0
  - @ai-accounts/vue-headless@0.1.0
