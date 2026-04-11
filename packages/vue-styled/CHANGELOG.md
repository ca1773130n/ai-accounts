# @ai-accounts/vue-styled

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
