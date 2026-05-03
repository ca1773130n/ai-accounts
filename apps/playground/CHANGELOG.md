# playground

## 0.0.5

### Patch Changes

- Mount `<AiChatPanel density="detailed">` below the accounts list once a ready backend exists.
- Per-row Remove button (confirm + `DELETE /api/v1/backends/{id}` + refresh).
- Header now exposes the primary "Add account" CTA instead of burying it inside a section; subtitle explains what the playground does.
- Account rows: per-kind colored left rail (claude orange / codex green / gemini blue / opencode purple), pill status badge with colored dot + glow on `ready`, monospace metadata chips, ellipsis-clamped name, hover lift.
- Empty state with primary CTA when no accounts.
- Modal: backdrop blur + click-outside-to-close.
- Card-style sections (`--pg-*` tokens), 960px container, 640px responsive breakpoint, properly sized chat panel (640px tall).
- Updated dependencies
  - @ai-accounts/ts-core@0.3.9
  - @ai-accounts/vue-headless@0.3.9
  - @ai-accounts/vue-styled@0.3.9

## 0.0.4

### Patch Changes

- Updated dependencies
  - @ai-accounts/ts-core@0.2.2
  - @ai-accounts/vue-headless@0.2.2
  - @ai-accounts/vue-styled@0.2.2

## 0.0.3

### Patch Changes

- Updated dependencies
  - @ai-accounts/ts-core@0.2.1
  - @ai-accounts/vue-headless@0.2.1
  - @ai-accounts/vue-styled@0.2.1

## 0.0.2

### Patch Changes

- Updated dependencies
  - @ai-accounts/ts-core@0.2.0
  - @ai-accounts/vue-headless@0.2.0
  - @ai-accounts/vue-styled@0.2.0

## 0.0.1

### Patch Changes

- Updated dependencies
  - @ai-accounts/ts-core@0.1.0
  - @ai-accounts/vue-headless@0.1.0
  - @ai-accounts/vue-styled@0.1.0
