# @ai-accounts/vue-headless

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
