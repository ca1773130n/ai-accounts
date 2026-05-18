# @ai-accounts/vue-headless

## 0.3.12

### Patch Changes

- Updated dependencies: `@ai-accounts/ts-core@0.3.12` (auto-discovery client methods).

## 0.3.11

### Patch Changes

- `useLoginSession.write_eager(text)` for direct PTY writes when the CLI never emits a textPrompt — gemini api_key flow needs this.
- `useLoginSession.reset()` for re-opening the wizard against the same backend.
- Updated dependencies: `@ai-accounts/ts-core@0.3.11`.

## 0.3.10

### Patch Changes

- Updated dependencies: `@ai-accounts/ts-core@0.3.10` (live model discovery surface).

## 0.3.9

### Patch Changes

- Add `useSmartChat.resetSession()` — drops `sessionId` + visible chat state so consumers can start a fresh conversation when the user switches backend (server-side sessions are bound to their original `backend_id`).
- `useSmartChat.dispatch` now propagates `backend_kind` + `account_label` from `backend_*` SSE events into `BackendResponseState.{backendKind, accountLabel}` so chat-panel cards can render proper kind + account labels instead of `bkd-…` hashes.
- `BackendResponseState` gained `backendKind` + `accountLabel` optional fields.
- Updated dependencies (chat type changes from ts-core)
  - @ai-accounts/ts-core@0.3.9

> Versions 0.2.3 through 0.3.8 backfilled from git log on 2026-05-04 — entries below.

## 0.3.8

### Patch Changes

- New `useLoginSession.reset()` for the wizard's "Add another account" flow (clears prior URL/status/error so a fresh add doesn't show stale state).
- Updated dependencies: `@ai-accounts/ts-core@0.3.8`.

## 0.3.7

### Patch Changes

- `useLoginSession.writeEager(text)` for the direct-PTY-write fallback path (Claude CLI v2 sometimes never emits the paste-code prompt).
- Updated dependencies: `@ai-accounts/ts-core@0.3.7`.

## 0.3.6

### Patch Changes

- No public composable changes; vue-styled's eager paste-code UX uses existing hooks.
- Updated dependencies: `@ai-accounts/ts-core@0.3.6`.

## 0.3.5

### Patch Changes

- Updated dependencies: `@ai-accounts/ts-core@0.3.5` (CRLF SSE parser fix unblocks login wizard end-to-end).

## 0.3.4

### Patch Changes

- Updated dependencies: `@ai-accounts/ts-core@0.3.4`.

## 0.3.3

### Patch Changes

- `useLoginSession` UrlPrompt cache → SSE replay surface for late subscribers (page refresh / network blip mid-OAuth no longer leaves the spinner stuck).
- Updated dependencies: `@ai-accounts/ts-core@0.3.3`.

## 0.3.0 — 0.3.2

### Minor / Patch Changes

- `useSmartChat` + `useSmartScroll` composables — single / all / compound modes, tool-call process groups, resilient streaming with replay-on-reconnect.
- Per-session locks in chat state (no global serialization).
- `injection-keys`, `aiAccountsKey` typed inject helpers.
- Updated dependencies through `@ai-accounts/ts-core@0.3.2`.

See root `CHANGELOG.md` `## 0.3.2` and `## 0.3.1` for the full release narrative.

## 0.2.2

### Patch Changes

- Fix AiAccountsClient constructor binding global `fetch` to the instance, which triggered "Illegal invocation" in browsers. Now wraps the default fetch so it's called against the global scope. Caller-supplied fetch is passed through unchanged.
- Updated dependencies
  - @ai-accounts/ts-core@0.2.2

## 0.2.1

### Patch Changes

- Add PATCH /api/v1/backends/{id} route, AccountService.update(), and AiAccountsClient.updateBackend() for editing backend display_name and config after creation.
- Updated dependencies
  - @ai-accounts/ts-core@0.2.1

## 0.2.0

### Minor Changes

- Add OnboardingFlow, Gemini + Codex backends with OAuth device flow, and per-account isolation directories.

  BREAKING: BackendProtocol.login() now returns LoginResult (tagged union of CredentialLogin, OAuthDeviceLogin, LoginError) and takes isolation_dir: Path. All validate/list_models/chat/pty methods also require isolation_dir. New poll_login() method. AccountService constructor now requires isolation_base_dir. AiAccountsClient.loginBackend() TypeScript return type changes from unknown to LoginResponseDTO.

### Patch Changes

- Updated dependencies
  - @ai-accounts/ts-core@0.2.0

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
