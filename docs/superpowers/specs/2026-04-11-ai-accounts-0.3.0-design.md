# ai-accounts 0.3.0 — "Real Extraction" Design

**Status:** Approved for planning
**Date:** 2026-04-11
**Supersedes:** `2026-04-11-ai-accounts-package-design.md` (0.1–0.2.x direction)
**Target repo:** `github.com/ca1773130n/ai-accounts`
**Consumer:** `github.com/ca1773130n/Agented` (branch `feat/ai-accounts-phase-1`, evolved)

## Problem

ai-accounts 0.1–0.2.x extracted the wrong layer. It shipped the data model (Backend rows, AccountService CRUD, PATCH routes, generic `<AccountWizard>` stub) and left the *valuable* layer — the polished 1947-line wizard with CLI-based OAuth, SSE-streamed subprocess orchestration, per-backend login metadata, chat panel, and PTY session management — in Agented. As a result:

- Agented's onboarding UX regressed twice when the shim tried to map ai-accounts' flat row shape to Agented's "one backend per kind with N accounts" model.
- Third parties gain nothing useful: a typed CRUD API for account rows is not why someone reaches for this package.
- The `BackendProtocol.login()` sync-return shape cannot express real interactive CLI flows (`claude /login` prints a URL, waits for callback, may prompt).

0.3.0 is a clean-break redesign that moves the actual value layer into the package.

## Goals

1. **Drop-in reusability.** `app.use(aiAccountsPlugin, {...})` in TS and `registerBackend()` in Python give any host app Agented's full AI backend experience: account wizard, real CLI-based OAuth, chat panel, interactive PTY sessions.
2. **Clean protocol boundary.** `BackendProtocol` is the sole Python extension point. Adding a new AI CLI means one Python class and registering its metadata.
3. **Agented becomes a thin consumer.** Zero shim logic in `frontend/src/services/api/backends.ts` (the file is deleted). `backend_cli_service.py`, `pty_service.py`, and the `/admin/backends/<kind>/connect` route family are deleted from Agented and live in ai-accounts.
4. **Stable contracts.** Types, events, and protocols frozen at `0.3.0` stable; breaking changes require `0.4.0`.

## Non-Goals

- Backwards compatibility with 0.2.x. Only Agented uses it; 0.2.x npm/PyPI tags are yanked with a deprecation note.
- Pinia or any external state library dependency on consumers.
- `node-pty`. Python's stdlib `pty` stays canonical; the frontend talks to the backend PTY over WebSocket.
- Multi-user auth, cloud storage, telemetry. Host apps plug these in via the event bus and `authHeaders` hook.

## In-Scope Surfaces

- Account wizard with real CLI-based OAuth (`cli_browser` flow), OAuth device flow, and API-key flow
- Backend metadata API (`/api/v1/backends/_meta`) served from Python source of truth
- `LoginSession` abstraction for interactive login flows
- Chat panel (messages, streaming, tool-call display)
- PTY session management (spawn, attach, stream, resize, signal, detach, reattach, kill)
- SQLite storage owned by ai-accounts (conversations, messages, pty_sessions, pty_frames)
- Event bus + `authHeaders` hook for host integration
- Agented migration (keep sidecar architecture, evolve from the existing branch)

## Architecture

### Two-process model

- Host app (Agented: Flask on :20000) owns its own concerns.
- ai-accounts Litestar ASGI sidecar on :20001 owns every `/api/v1/*` HTTP endpoint and every `/ws/*` WebSocket upgrade.
- Host's vite dev server (or equivalent production proxy) routes `/api/v1/*` and `/ws/*` to :20001.

This preserves the migration branch's plumbing. WebSocket proxying requires `ws: true` in the vite proxy config — added in alpha.3.

### Python packages

```
ai-accounts-core             Backends, protocols, storage, vault, metadata, login
  backends/                  Claude, Codex, Gemini, OpenCode + BackendProtocol + metadata
  login/                     LoginSession ABC, CLI orchestrator, LoginEvent union
  metadata/                  BackendRegistry, /_meta aggregation
  protocols/                 StorageProtocol, VaultProtocol, AuthProtocol (existing)
  adapters/                  SQLite storage, EnvKey vault, NoAuth/BearerAuth (existing)
  services/                  AccountService (existing, grown)

ai-accounts-sessions-core    Chat + PTY shared concerns (NEW)
  chat/                      ConversationService, MessageStore, SSE helpers
  pty/                       PtySession (wraps stdlib pty), orchestrator, frame store, ANSI util
  schema.sql                 conversations, messages, pty_sessions, pty_frames

ai-accounts-litestar         HTTP / WebSocket surface
  routes/backends.py         list/create/update/delete/detect
  routes/login.py            /connect, /login/stream (SSE), /respond, /cancel
  routes/meta.py             /backends/_meta
  routes/conversations.py    Chat SSE + POST
  routes/pty.py              WebSocket handler
  app.py                     create_app factory (grows chat + pty wiring)
  config.py                  AiAccountsConfig (grows chat_store, pty_store, cors_ws)
```

### TypeScript packages

```
@ai-accounts/ts-core         Typed HTTP / SSE / WebSocket client
  client/index.ts            AiAccountsClient (existing, fetch binding fix retained)
  client/login-stream.ts     SSE consumer + POST respond/cancel helpers
  client/conversations.ts    Chat SSE consumer
  client/pty-socket.ts       WebSocket wrapper (reconnect, backpressure)
  types/                     Generated from Python msgspec schemas
  events.ts                  AiAccountsEvent discriminated union

@ai-accounts/vue-headless    Unstyled primitives + stores + plugin
  plugin.ts                  app.use(aiAccountsPlugin, opts)
  composables/
    useAiAccounts.ts         Inject client
    useBackendRegistry.ts    Fetch /_meta, reactive backend list
    useLoginSession.ts       State machine for a single login flow
    useConversation.ts       Chat state
    usePtySession.ts         PTY state + WS lifecycle
  stores/                    Reactive stores (ref-based, no pinia)

@ai-accounts/vue-styled      Polished components (NEW in 0.3.0: the REAL wizard)
  AccountWizard.vue          The 1947-line wizard, refactored to use plugin + props
  BackendPicker.vue          Split out of wizard
  LoginStream.vue            URL prompt, text prompt, stdout display
  AccountEditForm.vue        Inline edit (restored from Agented)
  tokens.css                 Design tokens

@ai-accounts/vue-sessions    Chat + Terminal UI (NEW)
  ChatPanel.vue              Message list + composer
  ChatMessage.vue            Single message with tool-call rendering
  TerminalView.vue           xterm.js wrapper, WS-bound, resize + fit + copy/paste
  SessionList.vue            List of past PTY/chat sessions
  LogView.vue                Non-interactive fallback (plain scrollback)
```

### Data flows

**Login (SSE + POST):**
```
Wizard → POST /api/v1/backends/{kind}/connect            → BackendService.begin_login() → LoginSession
Wizard ← GET  /api/v1/backends/{id}/login/stream (SSE)   ← LoginSession.events()
Wizard → POST /api/v1/backends/{id}/login/respond        → LoginSession.respond(answer)
Wizard → POST /api/v1/backends/{id}/login/cancel         → LoginSession.cancel()
```

**Chat (SSE + POST, as Agented today):**
```
ChatPanel → POST /api/v1/conversations/{id}/messages
ChatPanel ← GET  /api/v1/conversations/{id}/stream (SSE)
```

**PTY (WebSocket, duplex):**
```
TerminalView ↔ WS /ws/pty/{session_id}
  client → server: {type: 'stdin', data},
                   {type: 'resize', cols, rows},
                   {type: 'signal', sig}
  server → client: {type: 'stdout', data},
                   {type: 'exit', code}
```

### Host integration

```ts
app.use(aiAccountsPlugin, {
  baseUrl: '/api/v1',
  wsBaseUrl: '/ws',
  authHeaders: () => ({ Authorization: `Bearer ${token.value}` }),
  onEvent: (evt) => { tour.notify(evt); analytics.track(evt); audit.record(evt); },
})
```

The plugin installs a typed event bus, an auth-header provider, and injects the `AiAccountsClient`. Consumers that don't need any of these get sensible defaults (no auth headers, no-op event handler).

## Key Type Contracts

These are frozen at `0.3.0` stable. Alphas may break them.

### BackendProtocol (Python)

```python
class BackendProtocol(Protocol):
    kind: ClassVar[str]
    metadata: ClassVar[BackendMetadata]

    async def detect(self) -> DetectResult: ...
    async def validate(self, config: dict, vault_ctx: VaultContext) -> ValidateResult: ...
    async def list_models(self, config: dict, vault_ctx: VaultContext) -> list[Model]: ...

    def begin_login(
        self,
        flow_kind: str,               # 'api_key' | 'oauth_device' | 'cli_browser'
        config: dict,
        vault_ctx: VaultContext,
        isolation_dir: Path,
    ) -> LoginSession: ...
```

### LoginSession (Python) — the central new abstraction

```python
class LoginSession(ABC):
    session_id: str
    backend_kind: str
    flow_kind: str

    @abstractmethod
    async def events(self) -> AsyncIterator[LoginEvent]: ...

    @abstractmethod
    async def respond(self, answer: PromptAnswer) -> None: ...

    @abstractmethod
    async def cancel(self) -> None: ...

    @property
    @abstractmethod
    def done(self) -> bool: ...
```

Implementations hold an internal `asyncio.Queue` for prompt answers; `respond()` puts onto it, the backend's login coroutine awaits on it. Timeouts and cancellation propagate through normal asyncio semantics.

### LoginEvent (discriminated union)

```python
LoginEvent = (
    UrlPrompt          # {url, user_code?} — show to user; external callback completes it
    | TextPrompt       # {prompt, hidden} — ask user for input; wait for respond()
    | StdoutChunk      # {text} — stream CLI stdout, ANSI-stripped
    | ProgressUpdate   # {label, percent?} — "polling...", "verifying..."
    | LoginComplete    # {account_id, backend_status}
    | LoginFailed      # {code, message}
)
```

### BackendMetadata (msgspec Struct)

```python
class BackendMetadata(Struct):
    kind: str
    display_name: str
    icon_url: str | None
    install_check: InstallCheck           # command + parse strategy for version
    login_flows: list[LoginFlowSpec]      # supported flows + UI hints
    plan_options: list[PlanOption] | None # e.g. Claude Pro / Max tiers
    config_schema: dict                   # JSON Schema for per-account edit form
    supports_multi_account: bool
    isolation_env_var: str | None         # CLAUDE_CONFIG_DIR / CODEX_HOME / GEMINI_CLI_HOME
```

Served aggregated at `GET /api/v1/backends/_meta`. The Vue plugin fetches this at app init and populates the reactive backend registry.

### PtySession (Python)

```python
class PtySession:
    session_id: str
    account_id: str
    backend_kind: str
    created_at: datetime
    cols: int
    rows: int

    async def attach(self) -> AsyncIterator[PtyFrame]: ...
    async def write(self, data: bytes) -> None: ...
    async def resize(self, cols: int, rows: int) -> None: ...
    async def signal(self, sig: int) -> None: ...
    async def close(self) -> None: ...
```

Detach/reattach is supported: frames are stored in `pty_frames` table; a late attacher replays recent frames then tails live.

### AiAccountsEvent (TypeScript discriminated union)

```ts
type AiAccountsEvent =
  | { type: 'wizard.opened', backendKind: string }
  | { type: 'wizard.step', backendKind: string, step: string }
  | { type: 'wizard.account.created', backendKind: string, accountId: string }
  | { type: 'wizard.closed', backendKind: string, reason: 'done'|'skip'|'cancel' }
  | { type: 'login.started', sessionId: string, backendKind: string, flow: string }
  | { type: 'login.prompt', sessionId: string, promptKind: 'url'|'text' }
  | { type: 'login.completed', sessionId: string, accountId: string }
  | { type: 'login.failed', sessionId: string, code: string, message: string }
  | { type: 'session.chat.started', conversationId: string, accountId: string }
  | { type: 'session.chat.message', conversationId: string, role: 'user'|'assistant' }
  | { type: 'session.pty.started', sessionId: string, accountId: string }
  | { type: 'session.pty.exited', sessionId: string, code: number }
  | { type: 'internal.handler_error', error: string, original: AiAccountsEvent }
```

The plugin wraps every `onEvent` handler call in try/catch; handler exceptions become `internal.handler_error` events and never propagate out of the bus.

## Storage

ai-accounts owns the conversation and session tables. Agented migrates via a one-shot helper script.

```sql
-- Existing in 0.2.x, unchanged
CREATE TABLE backends (...);

-- New in 0.3.0 (sessions-core)
CREATE TABLE conversations (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES backends(id),
  title TEXT,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL,          -- 'user' | 'assistant' | 'tool'
  content TEXT NOT NULL,
  tool_calls TEXT,             -- JSON
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE pty_sessions (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES backends(id),
  backend_kind TEXT NOT NULL,
  command TEXT NOT NULL,       -- JSON argv
  cols INTEGER NOT NULL,
  rows INTEGER NOT NULL,
  status TEXT NOT NULL,        -- 'running' | 'exited' | 'killed'
  exit_code INTEGER,
  created_at TIMESTAMP NOT NULL,
  ended_at TIMESTAMP
);

CREATE TABLE pty_frames (
  session_id TEXT NOT NULL REFERENCES pty_sessions(id),
  seq INTEGER NOT NULL,
  ts TIMESTAMP NOT NULL,
  kind TEXT NOT NULL,          -- 'stdout' | 'stdin' | 'resize' | 'signal' | 'exit'
  data BLOB NOT NULL,
  PRIMARY KEY (session_id, seq)
);
```

Agented migration helper (`scripts/migrate_to_0_3_0.py`): copies existing `conversations` / `messages` rows from Agented's DB into ai-accounts' sidecar DB. Keeps a pre-migration dump. Idempotent.

## Sequencing

Shipped as alpha tags so Agented dogfoods each slice before the next locks in.

### `0.3.0-alpha.1` — Wizard + Login (~3 weeks)

- Port `backend_cli_service.py` into `ai-accounts-core/login/cli_orchestrator.py`
- Define `LoginSession`, `LoginEvent`, new `BackendProtocol.begin_login()`
- Port Claude / Codex / Gemini / OpenCode login flows as `LoginSession` subclasses
- New routes: `/connect`, `/login/stream` (SSE), `/login/respond`, `/login/cancel`, `/backends/_meta`
- Port `AccountWizard.vue` into `@ai-accounts/vue-styled`, refactored to use plugin + props, no Agented imports
- Port `<AccountEditForm>` (inline edit restored)
- ts-core: `LoginStreamClient` + `useLoginSession` composable in vue-headless
- Event bus + `authHeaders` plugin wiring
- **Agented milestone:** delete `frontend/src/services/api/backends.ts` shim; wire packaged `<AccountWizard>`. This is the regression fix point — if alpha.1 is wrong, we fix before touching sessions.

### `0.3.0-alpha.2` — Chat (~2 weeks)

- `ai-accounts-sessions-core/chat/` — service, store, SSE streaming
- SQLite schema for conversations / messages
- `/api/v1/conversations/*` routes
- `@ai-accounts/vue-sessions/ChatPanel.vue` — ported from Agented's conversation UI
- `@ai-accounts/vue-sessions/ChatMessage.vue` with tool-call rendering
- Agented migration helper: copy existing chat data into ai-accounts' DB
- **Agented milestone:** BackendDetailPage chat drawer uses packaged `<ChatPanel>`

### `0.3.0-alpha.3` — PTY (~3 weeks)

- `ai-accounts-sessions-core/pty/` — port Agented's `pty_service.py`
- PtySession lifecycle (spawn/attach/detach/kill) + frame store
- Litestar WebSocket handler at `/ws/pty/{session_id}`
- ts-core `PtySocket` client (reconnect, backpressure)
- `@ai-accounts/vue-sessions/TerminalView.vue` with xterm.js + addon-fit
- Session detach / reattach via frame replay
- **Agented milestone:** interactive terminal view available for every account; execution logs keep using `<LogView>` for non-interactive output

### `0.3.0` stable (~1 week)

- Contract freeze; docs finalized; deprecation notice on 0.2.x
- Agented migration branch lands on main
- Yank 0.2.x npm/PyPI tags with "upgrade to 0.3.0" note
- Changelog, migration guide, example repo

**Total: ~9 weeks.** Each alpha is independently shippable and reviewable. If alpha.1 regresses Agented's onboarding, we stop and fix before alpha.2. No stacking broken layers.

## Migration from the Current Branch

The existing `feat/ai-accounts-phase-1` branch (14 commits, has sidecar + restored 1947-line wizard) is the base for 0.3.0 work, **not** abandoned. The sidecar architecture is correct.

**Kept from the branch:**
- Litestar sidecar on :20001
- `backend/scripts/run_ai_accounts.py` (grows to register the new login sessions)
- Vite proxy config for `/api/v1/*` (gets `/ws/*` added in alpha.3)
- The restored 1947-line `frontend/src/components/backends/AccountWizard.vue` — stays on main throughout alpha.1 as a fallback

**Deleted by alpha.1:**
- `frontend/src/services/api/backends.ts` shim (delete at end of alpha.1 after packaged wizard verified)
- The stub 0.2.x `<AccountWizard>` in vue-styled (replaced with the real one)

**Deleted by alpha.2:**
- `backend/app/services/backend_cli_service.py` (logic in ai-accounts-core/login)

**Deleted by alpha.3:**
- `backend/app/services/pty_service.py` (logic in ai-accounts-sessions-core/pty)
- `backend/app/services/chat_state_service.py` delegates to ai-accounts ConversationService

**At 0.3.0 stable:**
- Agented-local `AccountWizard.vue` deleted; imports come from `@ai-accounts/vue-styled`

## Testing & Risk Mitigation

Given the prior failure (shipped wrong direction, regressed onboarding UX twice), this is its own section.

### Testing per alpha

**alpha.1 — Wizard + Login:**
- Python integration tests for each `LoginSession` subclass with a fake CLI subprocess (pytest fixture mocking `pty.spawn` output)
- Vue component tests for `<AccountWizard>` with a mock `LoginStreamClient`, covering every step transition (welcome → install check → config → login → verify → done)
- **Manual E2E before alpha.2 starts:** user runs Agented locally with alpha.1 installed and goes through the real `claude /login` flow. No skipping.

**alpha.2 — Chat:**
- ConversationService unit tests with real SQLite
- `<ChatPanel>` component tests with mocked SSE
- E2E: send a message, receive streamed chunks through Agented's existing bot execution path

**alpha.3 — PTY:**
- PtySession tests with a scripted child (`bash -c 'echo hi; read x; echo $x'`)
- xterm.js WS integration test (jsdom-mounted TerminalView with mock WebSocket, or Playwright)
- Detach/reattach test with frame replay
- **Manual E2E:** user runs `claude` and `codex` interactively inside TerminalView, including TUI rendering

### Regression guards

1. **Visual snapshot tests** for every wizard step so "why did you remove edit" and "why is it asking choose AI service" can't happen silently.
2. **Explicit contract tests.** Every `AiAccountsEvent` variant has a test that fires it. Every `BackendMetadata.login_flows` combo is exercised.
3. **Agented dogfood gate between alphas.** User validates end-to-end in Agented before the next alpha merges. No ship-blind.
4. **No silent UI substitutions.** If a UI element can't be fully ported in an alpha, the alpha doesn't ship. No stub fallbacks.
5. **Keep the 1947-line wizard restored on main throughout.** Alpha branches rebase onto it; only alpha.1's final PR deletes the Agented-local copy, after the packaged version is verified.

### Risk register

| Risk | Mitigation |
|---|---|
| `LoginSession` abstraction doesn't fit real CLI flows | Alpha.1 ports all four backends before freezing the ABC — if one doesn't fit, the ABC changes |
| xterm.js breaks resize / paste / TUI rendering | Alpha.3 E2E runs real `claude` and real `codex`, not just `echo` |
| SQLite schema migration corrupts Agented's existing chat data | Migration helper runs on a DB copy first; keeps a pre-migration dump |
| WebSocket proxy doesn't work through vite dev server | Add `ws: true` to vite proxy in alpha.3; E2E test under `just dev-frontend` |
| Third-party event bus handler throws | Plugin wraps handlers in try/catch; exceptions become `internal.handler_error` events, never propagate |
| Concurrent login session cleanup (orphan subprocess) | LoginSession owns its subprocess; `cancel()` is idempotent and SIGKILLs on timeout |
| Per-account isolation dir collisions | `isolation_dir` is always account-scoped (`{backend_dirs_path}/{account_id}/`); tests enforce uniqueness |

## Acceptance Criteria for `0.3.0` Stable

- All Agented onboarding flows that worked on main at commit `6b15108` work identically through the package
- `frontend/src/services/api/backends.ts` shim is deleted
- `backend/app/services/backend_cli_service.py` is deleted
- `backend/app/services/pty_service.py` is deleted
- `backend/app/services/chat_state_service.py` delegates to ai-accounts' ConversationService
- `cd backend && uv run pytest` passes
- `cd frontend && npm run test:run` passes
- `just build` passes (vue-tsc + vite)
- **Manual E2E:** fresh clone of Agented → onboarding → create Claude account via `/login` → chat → interactive terminal session, all working
- Agented has zero imports from Agented-local backend wizard / PTY / chat services; all come from `@ai-accounts/*` and the Litestar sidecar
- `ai-accounts@0.3.0` published to npm (all packages) and PyPI (all packages)
- 0.2.x tags yanked with deprecation notice
- Changelog + migration guide published

## Open Questions

None at time of writing. All architectural decisions are locked. Implementation details (exact endpoint shapes, SQL index choices, xterm.js addon list) are deferred to the per-alpha implementation plan produced by `writing-plans`.
