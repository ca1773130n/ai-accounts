# Agented Consumer Integration of ai-accounts — Deep Dive

## 1. Sidecar Setup (`backend/scripts/run_ai_accounts.py`)

**File:** `/Users/neo/Developer/Projects/Agented/backend/scripts/run_ai_accounts.py`

The script creates and starts a standalone Litestar ASGI app that runs on `127.0.0.1:20001`. It is the only process responsible for all `/api/v1/*` traffic.

**Registered backends** (line 19-25):
- `ClaudeBackend()` — Anthropic Claude via the `claude` CLI
- `OpenCodeBackend()` — OpenCode open-source router
- `GeminiBackend()` — Google Gemini via `gemini` CLI
- `CodexBackend()` — OpenAI Codex via the `codex` CLI

**Config passed to `AiAccountsConfig`:**
- `env="development"` — enables dev-mode relaxed checks
- `storage=SqliteStorage("./ai_accounts.db")` — stores account rows in a local SQLite file relative to CWD (the project root when launched via `just`)
- `vault=EnvKeyVault.from_env(env="development")` — reads encryption keys from environment variables; in development this does not require a real key store
- `auth=NoAuth()` — all HTTP requests to the Litestar sidecar are unauthenticated; there is no token, API key, or session cookie injected at the HTTP layer (a follow-up is noted in `main.ts`)
- `backend_dirs_path=Path("./backend_dirs")` — where per-account CLI config directories are materialised on disk

**Port:** `uvicorn.run(app, host="127.0.0.1", port=20001)` — binds to loopback only; not accessible externally.

**Transitional note:** The file header comments that this is a "transitional arrangement" — as more features migrate to ai-accounts, Flask's responsibilities shrink.

---

## 2. Frontend Plugin Wiring (`frontend/src/main.ts`)

**File:** `/Users/neo/Developer/Projects/Agented/frontend/src/main.ts`

**Plugin installation (lines 27-39):**
```ts
const aiAccountsClient = new AiAccountsClient({ baseUrl: '' })
app.use(aiAccountsPlugin, {
  client: aiAccountsClient,
  onEvent: (event: AiAccountsEvent) => { ... notifyAiAccountsEvent(event) ... }
})
```

**`AiAccountsClient` config:** `baseUrl: ''` — all requests use relative URLs, meaning the Vite proxy resolves them. In production the same-origin static file serving handles the prefix split.

**`onEvent` handler:** Receives every `AiAccountsEvent` emitted by `@ai-accounts/vue-headless` (wizard lifecycle, login lifecycle, internal errors) and forwards to `notifyAiAccountsEvent()` from `useTourMachine.ts`. The call is wrapped in try/catch — tour bridging is explicitly "best-effort" and must never break the wizard UI.

**Auth headers:** The `token` property is not wired (noted as a follow-up). The `AiAccountsClient` is therefore calling `/api/v1/*` with no auth token. Agented's own Flask calls use `X-API-Key` from `localStorage` (via `getApiKey()` in `client.ts`), but the ai-accounts client instance in `main.ts` does not share that header. This is a known gap.

**Why a separate client in `main.ts` vs. the one in `backend-management.ts`:** The plugin-level client is installed into the Vue app so that `@ai-accounts/vue-headless` composables (e.g., `useAiAccounts()`) can inject it anywhere in the component tree. The module-level singleton in `backend-management.ts` exists for callers outside Vue setup contexts (router guards, test code, module-scope API helpers).

---

## 3. Wizard Integration (`frontend/src/views/BackendDetailPage.vue`)

**File:** `/Users/neo/Developer/Projects/Agented/frontend/src/views/BackendDetailPage.vue`

**Import (line 371):**
```ts
import { AccountWizard } from '@ai-accounts/vue-styled';
```
This is sourced entirely from the upstream package — there is no local `AccountWizard.vue` in `src/components/backends/` on this branch (it was deleted as part of T28/alpha.1).

**Usage (lines 136-145):**
```html
<AccountWizard
  v-if="showAddModal && !editingAccount && backend"
  :initial-backend-kind="backend.type"
  :backend-name="backend.name"
  @close="closeModal"
  @saved="onWizardSaved"
  @skip="onWizardSkip"
  @done="onWizardDone"
  @add-another="onWizardAddAnother"
/>
```

**Props:**
- `:initial-backend-kind` — passes `backend.type` (e.g., `"claude"`, `"gemini"`) to pre-select the backend in the wizard
- `:backend-name` — display name shown in the wizard header

**Event handlers:**
- `@close` → `closeModal()` — resets `showAddModal`, `editingAccount`, and clears all form state
- `@saved` → `onWizardSaved()` (line 553) — shows a success toast and reloads the backend data from the sidecar via `loadBackend()`
- `@skip` → `onWizardSkip()` (line 558) — closes the modal, shows an info toast, and calls `tourMachine.nextStep()` to advance the tour even though no account was added
- `@done` → `onWizardDone()` (line 564) — calls `closeModal()` then `tourMachine.nextStep()`
- `@add-another` → `onWizardAddAnother()` (line 569) — the wizard resets its own internal state; Agented just reloads backend data to reflect the newly added account

**Second `AiAccountsClient` instance (line 379):**
```ts
const aiAccountsClient = new AiAccountsClient({ baseUrl: '' });
```
This component-scoped instance is used directly for `updateBackend()` (save edited account, line 590) and `deleteBackend()` (line 615). This is a deliberate choice: these two mutations do not need the plugin event bus, so using the composable would be over-engineering.

---

## 4. Tour Machine Integration (`frontend/src/composables/useTourMachine.ts`)

**File:** `/Users/neo/Developer/Projects/Agented/frontend/src/composables/useTourMachine.ts`

### `runGuardChecks` — querying `/api/v1/backends/` (lines 119-151)

The function makes three parallel-ish fetch calls to determine onboarding completion status. The backends check is the ai-accounts integration point:

```ts
const backends = await fetchWithAuth<{ items: Array<{ id: string; kind: string }> }>(
  '/api/v1/backends/',
)
if (backends?.items) {
  results.hasAnyBackend = backends.items.length > 0
  results.hasClaudeAccount = backends.items.some((b) => b.kind === 'claude')
}
```

**Key architectural note:** The comment in the code (lines 133-136) explicitly documents the shape change:
- Legacy `/admin/backends` returned a nested shape keyed by kind with a `accounts` array.
- Current `/api/v1/backends/` (ai-accounts 0.3.0-alpha.1 flat model) returns `{items: [{id, kind, display_name, ...}]}` where each item is one account row.

The `fetchWithAuth` helper (lines 93-106) reads `X-API-Key` from localStorage and injects it as a header. This means the tour machine's guard check *does* pass the API key, unlike the plugin-level `AiAccountsClient`.

### `notifyAiAccountsEvent` — event bridge (lines 440-480)

This is the exported function called from `main.ts`'s `onEvent`. It operates on the shared singleton actor directly (not through `useTourMachine()`) so it is safe to call outside Vue setup context.

**Mapping:**
- `wizard.account.created` and `login.completed` → kick `runGuardChecks()` and if `backends.claude` step is active and `hasClaudeAccount` is now true, send `{ type: 'NEXT' }` to the XState actor
- All other event types → intentionally unhandled (observational; analytics hooks can layer on top)

**Guard-check-then-advance pattern:** Rather than wiring XState guards as synchronous conditions (which XState supports but which would require blocking fetch inside the machine), the pattern is: receive event → run async check → conditionally send a different event. This keeps the machine synchronous and easy to test.

---

## 5. Vite Proxy Config (`frontend/vite.config.ts`)

**File:** `/Users/neo/Developer/Projects/Agented/frontend/vite.config.ts`

The proxy table (lines 27-51, same in both `server` and `preview` blocks):

| Pattern | Target | Notes |
|---|---|---|
| `/api/v1` | `http://127.0.0.1:20001` | ai-accounts Litestar sidecar |
| `/api` | `http://127.0.0.1:20000` | Agented Flask backend |
| `/admin` | `http://127.0.0.1:20000` | Agented Flask admin routes |
| `/health` | `http://127.0.0.1:20000` | Flask health endpoint |
| `/docs` | `http://127.0.0.1:20000` | Flask OpenAPI docs |
| `/openapi` | `http://127.0.0.1:20000` | Flask OpenAPI schema |

**Critical ordering:** Vite evaluates proxy rules in definition order. `/api/v1` is declared first, so `GET /api/v1/backends/` routes to port 20001. Any other `/api/*` path falls through to port 20000 (Flask). This is the mechanism that separates the two backend processes with zero configuration change at the application level.

---

## 6. Full Data Flow Diagram

### (a) Listing backends

1. Component calls `listGroupedBackends()` from `backend-management.ts` (line 346)
2. → `aiAccountsClient.listBackends()` → `GET /api/v1/backends/` → Vite proxy → **Litestar :20001** → returns `{items: BackendDTO[]}`
3. → `tryDetect(kind, dtos)` per kind → `aiAccountsClient.detectBackend(dto.id)` → `GET /api/v1/backends/{id}/detect` → Litestar
4. → `buildGroupedBackend()` assembles the legacy `AIBackend` shape
5. → returns `{ backends: AIBackend[] }` to the component

### (b) Creating an account via wizard

1. User clicks "Add Account" → `showAddModal = true` → `<AccountWizard>` mounts
2. Wizard (internal to `@ai-accounts/vue-styled`) calls `AiAccountsClient.createBackend({ kind, display_name, config })` → `POST /api/v1/backends/` → Litestar → writes row to `ai_accounts.db`
3. Wizard emits `@saved` → `onWizardSaved()` → `loadBackend()` → `getGroupedBackend()` → `aiAccountsClient.listBackends()` → `GET /api/v1/backends/` → reflects new row
4. Wizard also emits the `wizard.account.created` `AiAccountsEvent` through the plugin event bus
5. `notifyAiAccountsEvent({ type: 'wizard.account.created', ... })` fires in `main.ts` `onEvent`
6. `runGuardChecks()` re-queries `GET /api/v1/backends/` and if `kind === 'claude'` is now present, sends `NEXT` to the tour XState actor
7. Tour advances to the next step; localStorage is updated via the actor's subscription

### (c) Logging in via cli_browser flow

1. User clicks "Login" in `BackendDetailPage` or the `AccountWizard` opens the login sub-flow
2. For the legacy path (AccountLoginModal): `backendManagementApi.startConnect(backendId, configPath)` → `POST /admin/backends/{id}/connect` → **Flask :20000** → spawns a PTY subprocess running the CLI's login command, returns `{ session_id }`
3. `createAuthenticatedEventSource('/admin/backends/{id}/connect/{sessionId}/stream')` → SSE stream from **Flask :20000** → delivers `log`, `prompt`, `completed` events in real time
4. On `prompt` events, user types a response → `backendManagementApi.respondConnect(backendId, sessionId, interactionId, response)` → `POST /admin/backends/{id}/connect/{sessionId}/respond` → **Flask :20000** → writes to the PTY stdin
5. On `completed` event → `emit('success')` → `onLoginModalSuccess()` → `loadBackend()`
6. For the new ai-accounts login path (wizard-internal): `AiAccountsClient.beginLogin()` → `POST /api/v1/backends/{id}/connect` → **Litestar :20001** → SSE stream via `GET /api/v1/login/stream/{sessionId}` — this path is what `AccountWizard` uses in alpha.1

### (d) CLIProxyAPI registration

1. `backendManagementApi.proxyLogin(backendType, configPath)` → `aiAccountsClient.cliproxyLoginBegin(kind, configPath)` → `POST /api/v1/cliproxy/login` → **Litestar :20001**
2. Litestar initiates the CLIProxy OAuth flow; returns `{ status, message, oauth_url?, device_code? }`
3. If `oauth_url` is returned, user opens it in their browser; the OAuth redirect URL is captured
4. `backendManagementApi.proxyCallbackForward(callbackUrl)` → `aiAccountsClient.cliproxyCallbackForward(callbackUrl)` → `POST /api/v1/cliproxy/callback` → **Litestar :20001** → completes authentication
5. `backendManagementApi.proxyStatus()` → `GET /admin/backends/proxy/status` → **Flask :20000** → introspects the CLIProxy account list from the Flask side (this endpoint has not yet migrated to the sidecar)

---

## 7. What Was Deleted and Why

**Deleted:** `frontend/src/services/api/backends.ts`

This was the old "grouped shim" API module. It contained:
- `backendApi` — a CRUD wrapper over Flask's `/admin/backends/*` endpoints for creating, updating, and deleting accounts
- `BACKEND_METADATA` — static metadata (name, description, documentation URL) for each CLI kind
- `BACKEND_LOGIN_INFO` (earlier version) — help-link constants
- The old `listBackends()` / `getBackend()` calls that returned the nested `{ backends: { claude: { accounts: [...] }, ... } }` shape

**Why deleted:** After T28 (the alpha.1 consumer cut), the account CRUD operations moved to the ai-accounts Litestar sidecar and are accessed via `AiAccountsClient` methods. The nested shape is no longer the source of truth — the flat `BackendDTO[]` from `/api/v1/backends/` is. `BACKEND_METADATA` was absorbed into `backend-management.ts` as the `BACKEND_METADATA` const (lines 240-266) which is used only by the transitional grouping helpers. `BACKEND_LOGIN_INFO` and `BACKEND_PLAN_OPTIONS` survived as Agented-local UI constants in `backend-management.ts` because they are Agented-specific (plan pricing, console URLs) and not appropriate for the upstream package.

**Deleted:** `frontend/src/components/backends/AccountWizard.vue`

This was Agented's own 1947-line implementation of the account add wizard, restored from git history (`6b15108^`). It handled:
- Backend picker step
- API-key entry step
- Config path entry step
- CLI login (TTY output via the Flask `/admin/backends/{id}/connect` SSE stream)
- Plan selection step

**Why deleted:** The entire wizard has been upstreamed into `@ai-accounts/vue-styled` as `AccountWizard.vue`. The package version is the authoritative implementation. Keeping the local copy would mean two diverging implementations of the same UI. The upstream version is wired to the Litestar sidecar login flow (`/api/v1/backends/{id}/connect`), replacing the Flask PTY path for new accounts.

**What remains in Agented that has NOT migrated:**
- `AccountLoginModal.vue` — still uses the Flask `/admin/backends/{id}/connect` SSE path (explicitly tagged `TODO(T29+)` in `backend-management.ts` lines 92-94)
- Rate limit checks, auth status polling, model discovery, test prompts, Gemini direct OAuth — all still on Flask `/admin/backends/*`
- CLIProxyAPI status/listing — the `proxyStatus()` and `listProxyAccounts()` methods still hit Flask (lines 137-141 of `backend-management.ts`)

---

## Essential Files

- `/Users/neo/Developer/Projects/Agented/backend/scripts/run_ai_accounts.py` — sidecar entry point and config
- `/Users/neo/Developer/Projects/Agented/frontend/src/main.ts` — plugin installation and event bridge wiring
- `/Users/neo/Developer/Projects/Agented/frontend/vite.config.ts` — proxy split between :20001 and :20000
- `/Users/neo/Developer/Projects/Agented/frontend/src/views/BackendDetailPage.vue` — AccountWizard consumer with tour integration
- `/Users/neo/Developer/Projects/Agented/frontend/src/composables/useTourMachine.ts` — guard check against `/api/v1/backends/` + `notifyAiAccountsEvent` bridge
- `/Users/neo/Developer/Projects/Agented/frontend/src/services/api/backend-management.ts` — transitional grouping helpers, `aiAccountsClient` singleton, Agented-local Flask wrappers
- `/Users/neo/Developer/Projects/Agented/frontend/src/services/api/client.ts` — `apiFetch` infrastructure, `X-API-Key` injection, SSE with backpressure
- `/Users/neo/Developer/Projects/Agented/frontend/src/services/api/index.ts` — barrel re-export; what is and is not exported shows the current migration boundary
- `/Users/neo/Developer/Projects/Agented/frontend/src/components/monitoring/AccountLoginModal.vue` — the remaining un-migrated login flow (Flask PTY path)
- `/Users/neo/Developer/Projects/Agented/docs/superpowers/plans/2026-04-11-ai-accounts-0.3.0-alpha.1.md` — the plan document that governs what was deleted and why