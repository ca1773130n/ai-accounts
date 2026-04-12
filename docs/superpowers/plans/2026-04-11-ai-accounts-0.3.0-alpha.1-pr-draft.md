# PR draft — ai-accounts 0.3.0-alpha.1 consumer migration

**Branch:** `feat/0.3.0-alpha.1-consumer` (Agented) — not yet pushed
**Base:** `feat/ai-accounts-phase-1`
**Target repo:** `github.com/ca1773130n/Agented`

## Title

`feat(backends): migrate to ai-accounts 0.3.0-alpha.1 (wizard + login)`

## Body

### Summary

Agented now consumes the freshly-published `ai-accounts@0.3.0-alpha.1` for AI backend account management, login, and onboarding. The local 1947-line `AccountWizard.vue` and the 447-line `backendApi` shim are deleted — the polished wizard, CLI-based OAuth orchestration, CLIProxyAPI registration, per-backend CLI auto-install, and Gemini direct-OAuth flow all live in the package now.

This replaces the directionally-wrong 0.1–0.2.x extraction (which packaged the data model but left the valuable UX layer in Agented) with a clean-break redesign around the `LoginSession` abstraction.

### What changed

**Python sidecar (`backend/scripts/run_ai_accounts.py`):**
- Bumped `ai-accounts-core` + `ai-accounts-litestar` to `0.3.0a1`
- Registers all four backends (Claude / Codex / Gemini / OpenCode) with their new `BackendProtocol` shape (`metadata` classvar + `begin_login()`)

**Frontend (`frontend/src/main.ts`):**
- Installs `aiAccountsPlugin` at app root with typed `AiAccountsEvent` event bus
- `useTourMachine` gains a `notify(event)` method that advances the onboarding tour on `wizard.account.created` and `login.completed`
- Event bus also routes to analytics/audit as needed (extendable)

**BackendDetailPage (`frontend/src/views/BackendDetailPage.vue`):**
- Imports `AccountWizard` from `@ai-accounts/vue-styled` instead of the local component
- Drops shim-based account grouping in favor of the flat `BackendDTO` model from the new client

**Deleted:**
- `frontend/src/services/api/backends.ts` (shim, 447 lines)
- `frontend/src/components/backends/AccountWizard.vue` (local wizard, 1947 lines)
- Every caller of the old shim migrated to `useAiAccounts().client` + `useBackendRegistry()`

### What the new wizard preserves

Port happened in `ai-accounts` at tag `v0.3.0-alpha.1`. The wizard's polished flow is preserved verbatim, with these features restored via new backend routes after the initial port flagged them as gaps:

- **Per-backend CLI auto-install** (`POST /api/v1/backends/{kind}/install`)
- **CLIProxyAPI install** (`POST /api/v1/cliproxy/install`)
- **CLIProxyAPI account registration** with device-code flow (`POST /api/v1/cliproxy/login/begin`) and remote-user callback paste (`POST /api/v1/cliproxy/login/callback-forward`)
- **Gemini direct OAuth** with PKCE + httpx token exchange + creds file write — available as a third `GeminiBackend` login flow (`flow_kind: "direct_oauth"`)

The wizard's 5-step flow (subscription → CLI → login → plan → done) now extends to 6 steps when the backend is proxy-compatible (claude/codex/gemini): subscription → CLI → login → **proxy** → plan → done. `VISIBLE_STEPS` is a `computed` that skips the proxy step for non-compatible backends.

### Architecture notes

- **Sidecar split preserved.** Flask on `:20000`, Litestar ASGI on `:20001`. Vite proxies `/api/v1/*` to 20001.
- **Clean break from 0.2.x.** `BackendProtocol.login()` / `poll_login()` removed; backends now implement `begin_login(flow_kind, config, vault_ctx, isolation_dir) -> LoginSession`. The `LoginSession` ABC yields `LoginEvent`s (URL prompt / text prompt / stdout / progress / complete / failed) over an async generator, with `respond(answer)` for text prompts and `cancel()` for abort. HTTP surface is SSE + POST: `/login/begin` + `/login/stream` + `/login/respond` + `/login/cancel`.
- **Typed event bus.** `AiAccountsEvent` discriminated union (`wizard.opened`, `wizard.step`, `wizard.account.created`, `wizard.closed`, `login.started`, `login.prompt`, `login.completed`, `login.failed`, `internal.handler_error`). Host wires a single `onEvent` handler; exceptions become `internal.handler_error` events and never propagate.
- **No Pinia dependency.** Reactive state uses `ref`/`reactive` + `provide/inject`.

### Test plan

- [x] `just build` — vue-tsc clean, vite build 5.43s
- [x] `cd backend && uv run pytest -q` — 3327 passed, 1 xfailed, 3 failed (3 failures reproduced on `feat/ai-accounts-phase-1` → **pre-existing, unrelated**)
- [x] `cd frontend && npm run test:run` — 1003 passed, 11 failed (11 failures reproduced on base → **pre-existing tour-machine tests**)
- [x] Sidecar smoke tests: `/health`, `/api/v1/backends/_meta` (all 4 backends with correct flows including Gemini `direct_oauth`), `/api/v1/cliproxy/status`, `POST /backends/`, `POST /login/begin`, `DELETE /backends/{id}`
- [ ] **Manual E2E (required before merge):**
  - [ ] Claude `cli_browser` flow — run `claude /login` end-to-end through wizard
  - [ ] Claude `api_key` flow — paste a sk-ant- key
  - [ ] Codex `oauth_device` flow — real OpenAI device code
  - [ ] Codex `cli_browser` flow
  - [ ] Gemini `oauth_device` flow
  - [ ] **Gemini `direct_oauth` flow** (new in alpha.1) — Google consent + paste code
  - [ ] OpenCode `cli_browser` flow
  - [ ] CLIProxyAPI install (if not already present)
  - [ ] CLIProxyAPI Claude registration via device code
  - [ ] CLIProxyAPI callback paste path for remote/tunnel setups
  - [ ] Inline account edit form (edit display_name + config)
  - [ ] Account delete
  - [ ] Add-another flow from done step
  - [ ] Tour advancement via `useTourMachine.notify` on `wizard.account.created`

### Rollback

If alpha.1 misbehaves in production:
1. Revert commits `272b28b..a7b0b81` on Agented
2. Re-install `@ai-accounts/*` at last known good version (`0.2.2`)
3. Restore `backend_cli_service.py` from history (it's still in the removed-file list)
4. The sidecar can stay — it's an ASGI process; downgrading its deps is a `uv sync` away

### Related

- ai-accounts tag: `v0.3.0-alpha.1` (commit `8f76f7e`)
- ai-accounts PyPI: `ai-accounts-core==0.3.0a1`, `ai-accounts-litestar==0.3.0a1`
- ai-accounts npm: `@ai-accounts/ts-core@0.3.0-alpha.1`, `@ai-accounts/vue-headless@0.3.0-alpha.1`, `@ai-accounts/vue-styled@0.3.0-alpha.1` (alpha dist-tag)
- Design spec: `docs/superpowers/specs/2026-04-11-ai-accounts-0.3.0-design.md`
- Implementation plan: `docs/superpowers/plans/2026-04-11-ai-accounts-0.3.0-alpha.1.md`

### Follow-ups (deferred to 0.3.0-alpha.2 / .alpha.3)

- `0.3.0-alpha.2`: chat panel + conversation storage
- `0.3.0-alpha.3`: PTY session management with xterm.js
- `0.3.0` stable: contract freeze + 0.2.x deprecation
