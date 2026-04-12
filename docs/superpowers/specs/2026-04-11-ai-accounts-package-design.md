# ai-accounts — Reusable AI Backend, Chat, and PTY Package

**Status:** Design approved, ready for implementation planning
**Date:** 2026-04-11
**Author:** Brainstormed with Claude
**License target:** Apache-2.0

## Summary

Extract Agented's AI backend account management, onboarding, AI chat panel, CLI
proxy, PTY, and CLI session management into a standalone open-source package
(`ai-accounts`) that can be reused across unrelated projects. The package is
designed as a Python + TypeScript monorepo with a Protocol-based architecture:
small typed interfaces, zero-config default adapters, optional adapters shipped
as extras. The package dogfoods itself through Agented, which migrates feature
by feature onto the new package.

## Goals

- Ship a reusable OSS package that other projects can adopt without inheriting
  Agented-specific assumptions (Flask, SQLite paths, auth model, UI look).
- Replace Agented's own implementations of these features with the package,
  proving the abstractions under real use.
- Provide a clean extension model so third parties can add custom AI backends,
  storage engines, auth providers, and vault backends without forking.
- Keep the developer-facing API small, typed, and testable.

## Non-goals (v1)

- RBAC, multi-tenant user management, password/session/"forgot password" flows.
  The package authenticates callers via a pluggable Protocol but does not ship
  a full identity system.
- Flask support. Agented's existing Flask code coexists with the new Litestar
  app via ASGI mounting; no `ai-accounts-flask` adapter is shipped.
- Non-Vue frontend adapters (React/Svelte/Solid). The TS core is framework-
  agnostic so these can land later without breaking changes.
- Replacing Agented features outside the package's scope (bots, teams,
  executions, workflows, plugins, skills, rules, commands, hooks).

## Decisions locked during brainstorming

| # | Question | Decision |
|---|---|---|
| 1 | Target audience | Open-source, designed for unknown future projects |
| 2 | Backend framework | Litestar (ASGI, OpenAPI 3.1 native) |
| 3 | Storage | Protocol + aiosqlite default + optional SQLAlchemy extra |
| 4 | Scope | Accounts, auth, onboarding, chat, PTY, sessions, model discovery, cost, vault, history. No RBAC. |
| 5 | Frontend packaging | TS core + Vue 3 headless composables + Vue 3 styled components |
| 6 | Wire transport | Transport-agnostic protocol layer; SSE (chat) + WebSocket (PTY) as default HTTP transports; in-process default for embedding |
| 7 | Human auth | Pluggable `AuthProtocol`, ships `NoAuth` + `ApiKeyAuth`, optional `@ai-accounts/oidc` subpackage |
| 8 | Credential vault | Pluggable `VaultProtocol`, ships `EnvKeyVault` (AES-GCM), optional KMS and OS keychain adapters. Production-mode startup guard. |
| 9 | Repo layout | Single monorepo (`uv` + `pnpm` workspaces) |
| 10 | Extraction strategy | Greenfield new repo + Agented dogfoods it from day one via incremental feature migration (Q10 option C) |
| — | License | Apache-2.0 |
| — | Versioning | Changesets; lockstep during 0.x; strict semver from 1.0 |
| — | Docs | Vitepress site |
| — | Python / Node | Python 3.11+, Node 20+ |

## Architectural spine

Every layer follows the same pattern: typed Protocol, zero-config default
adapter, optional plug-in adapters shipped as extras.

```
Protocol (interface)   →  Default adapter (shipped)   →  Optional adapters (extras)
─────────────────────────────────────────────────────────────────────────────────
StorageProtocol        →  aiosqlite                    →  sqlalchemy
VaultProtocol          →  env-key AES-GCM              →  aws-kms, gcp-kms, vault, keychain
AuthProtocol           →  no-auth (dev) + api-key      →  oidc
BackendProtocol        →  built-in: claude, opencode, gemini, codex, ...
TransportProtocol      →  in-process async iterator    →  SSE, WebSocket
FrontendUIProtocol     →  Vue headless composables     →  Vue styled components
```

Consumers pick their seams. Hobbyists use the defaults and ship in an
afternoon. Enterprises plug in KMS and OIDC. Embedders (CLI tools, desktop
apps) skip HTTP entirely and iterate the in-process transport.

## Monorepo layout

```
ai-accounts/
├── packages/
│   ├── core/                      # Python, framework-free
│   │   ├── domain/                # msgspec structs
│   │   ├── protocols/             # Protocols (Storage, Vault, Auth, Backend, Transport)
│   │   ├── services/              # Pure async business logic
│   │   ├── protocol/              # Wire protocol: WireEvent tagged union
│   │   ├── transport/             # In-process / SSE / WebSocket adapters
│   │   ├── backends/              # Built-in Backend implementations (claude, opencode, gemini, codex, ...)
│   │   ├── adapters/
│   │   │   ├── storage_sqlite/    # aiosqlite, default
│   │   │   ├── vault_envkey/      # AES-GCM, default
│   │   │   ├── auth_noauth/       # dev-only default
│   │   │   └── auth_apikey/       # production-minimum default
│   │   └── testing/               # FakeStorage, FakeVault, FakeBackend, conformance suites
│   ├── litestar/                  # HTTP layer: routes, guards, OpenAPI
│   ├── oidc/                      # Optional: OIDC human-auth provider
│   ├── sqlalchemy/                # Optional: SQLAlchemy storage adapter
│   ├── aws-kms/                   # Optional: KMS vault adapter
│   ├── gcp-kms/                   # Optional: KMS vault adapter
│   ├── vault/                     # Optional: HashiCorp Vault adapter
│   ├── keychain/                  # Optional: OS keychain vault adapter
│   ├── ts-core/                   # TypeScript: protocol types, API client, state machines
│   ├── vue-headless/              # Vue 3 composables, zero CSS
│   └── vue-styled/                # Vue 3 components, CSS-var themeable
├── apps/
│   └── playground/                # Demo app: Litestar + Vue styled
├── docs/                          # Vitepress site
├── tests/
├── justfile                       # Top-level dispatch
├── uv.lock                        # Python workspace lock
├── pnpm-lock.yaml                 # JS workspace lock
└── .github/workflows/             # CI matrix
```

## Python core package (`packages/core`)

Framework-free Python. Every other Python package depends on `core`.

### Domain models (`core/domain/`)

msgspec `Struct` types:

- `Backend` — id, kind, display name, config, status
- `BackendCredential` — opaque ciphertext reference; never exposes plaintext
- `ChatSession`, `ChatMessage`, `ChatStreamEvent`
- `PtySession`, `PtyEvent`
- `OnboardingState`
- `Principal` — returned by `AuthProtocol.authenticate`

### Protocols (`core/protocols/`)

```python
class StorageProtocol(Protocol):
    async def backends(self) -> BackendRepository: ...
    async def sessions(self) -> SessionRepository: ...
    async def history(self) -> HistoryRepository: ...
    async def onboarding(self) -> OnboardingRepository: ...

class VaultProtocol(Protocol):
    async def encrypt(self, plaintext: bytes, *, context: dict) -> bytes: ...
    async def decrypt(self, ciphertext: bytes, *, context: dict) -> bytes: ...
    async def rotate(self, old_key_id: str) -> None: ...

class AuthProtocol(Protocol):
    async def authenticate(self, request_ctx: RequestContext) -> Principal | None: ...

class BackendProtocol(Protocol):
    kind: ClassVar[str]
    async def detect(self) -> DetectResult: ...
    async def login(self, flow: LoginFlow) -> Credential: ...
    async def validate(self, credential: Credential) -> bool: ...
    async def list_models(self, credential: Credential) -> list[Model]: ...
    async def chat(self, req: ChatRequest, credential: Credential) -> AsyncIterator[ChatStreamEvent]: ...
    async def pty(self, req: PtyRequest, credential: Credential) -> PtyHandle: ...

class TransportProtocol(Protocol):
    async def send(self, event: WireEvent) -> None: ...
    def receive(self) -> AsyncIterator[WireEvent]: ...
```

Each Protocol is small and independently testable with in-memory fakes.

### Services (`core/services/`)

Pure async business logic. Dependencies injected via constructor — no globals,
no module-level state. This is what lets consumers embed the library in-process
without HTTP.

- `AccountService` — CRUD on backends; wraps Vault for credential sealing
- `OnboardingService` — first-run wizard state machine
- `ChatService` — orchestrates a chat turn: load credential, stream through backend, persist history, emit wire events
- `PtyService` — spawn/attach/resize/kill; bridges subprocess to wire transport
- `SessionService` — tracks live chat+PTY sessions, enforces limits, cleans up on disconnect
- `ModelDiscoveryService` — lists models per backend, caches results
- `CostService` — tallies tokens and dollars per session

### Built-in backends (`core/backends/`)

One module per AI CLI (`claude.py`, `opencode.py`, `gemini.py`, `codex.py`,
...). Each implements `BackendProtocol`. Bulk of the logic is subprocess
lifecycle + protocol translation. This is where most of Agented's current
`backend_cli_service.py` and `cliproxy_chat_service.py` lands.

### Wire protocol (`core/protocol/`)

Typed message schemas shared with TypeScript. `WireEvent` tagged union:
`ChatTokenEvent`, `ChatDoneEvent`, `PtyOutputEvent`, `PtyResizeEvent`,
`SessionStartEvent`, `SessionEndEvent`, `ErrorEvent`, etc.

- Defined in Python with msgspec.
- Codegen emits matching TypeScript types for `ts-core`. CI fails if generated
  files drift from the committed copies.
- Wire protocol has its own version field (`WireEvent.protocol_version`);
  server advertises supported versions, client negotiates on connect.

### Transport (`core/transport/`)

- `InProcessTransport` — default, zero dependencies, pass-through async iterator
- `SseTransport` — formats WireEvents as SSE `data:` lines
- `WebSocketTransport` — sends WireEvents as msgspec-encoded frames

Core never imports Litestar. Transport is chosen by the Litestar layer per
route.

### Stability of `BackendProtocol`

Because third parties will write custom backends, `BackendProtocol` breakage is
expensive. Versioned explicitly as `BackendProtocolV1`; additive-only changes
within a major version of the package.

## Litestar HTTP layer (`packages/litestar`)

Thin wrapper over `core`. Owns routes, guards, OpenAPI, SSE/WebSocket handlers.
Zero business logic.

### Composition entry point

```python
from ai_accounts.litestar import create_app, AiAccountsConfig
from ai_accounts.adapters.storage_sqlite import SqliteStorage
from ai_accounts.adapters.vault_envkey import EnvKeyVault
from ai_accounts.adapters.auth_apikey import ApiKeyAuth
from ai_accounts.backends import ClaudeBackend, OpenCodeBackend, GeminiBackend

app = create_app(AiAccountsConfig(
    storage=SqliteStorage("./accounts.db"),
    vault=EnvKeyVault.from_env(),      # raises if AI_ACCOUNTS_VAULT_KEY missing in prod
    auth=ApiKeyAuth.from_env(),
    backends=[ClaudeBackend(), OpenCodeBackend(), GeminiBackend()],
    env="production",
    cors_origins=["http://localhost:3000"],
))
```

Consumers who already have a Litestar app call `build_router(config)` and
attach the router manually.

### Routes

- `/api/v1/backends` — CRUD, detect, validate
- `/api/v1/onboarding` — wizard state machine
- `/api/v1/chat` — POST messages, SSE stream
- `/api/v1/pty` — WebSocket
- `/api/v1/sessions` — list, kill, resize
- `/api/v1/models` — discovery, pricing
- `/api/v1/usage` — cost reports

### Route design rules

- OpenAPI 3.1 first-class; spec served at `/schema`.
- `ts-core` codegens its API client from the OpenAPI spec.
- SSE for chat with `Last-Event-ID` reconnect.
- WebSocket for PTY: binary frames for stdout, control frames for resize/signals.
- Single exception handler maps domain exceptions to a uniform envelope
  `{error: {code, message, details?}}`, documented in OpenAPI so TS clients can
  discriminate on `code`.

### Production-mode startup guard

`create_app(env="production")` validates on startup:

- Vault has a real key loaded from `AI_ACCOUNTS_VAULT_KEY` or an explicit key file — not the dev-derived fallback.
- Auth is not `NoAuth`.
- CORS is not `*`.

Fails fast with an error listing every violation. Prevents the classic
"shipped with default key" CVE.

In dev mode (`env="development"` or unset), `EnvKeyVault` falls back to a
derived key computed from a stable local secret, with a loud warning logged on
every startup. This keeps `git clone && just dev` friction-free while making
the insecure path obviously not-for-production.

### Expected size

~800–1200 lines total. If it grows larger, logic has leaked out of `core`.

## TypeScript & Vue packages

Three JS packages mirroring the Python core/adapter pattern.

### `packages/ts-core` — framework-agnostic TypeScript

Zero framework deps. Consumable from Vue, React, Svelte, Solid, Node, Electron,
or vanilla.

```
packages/ts-core/
├── src/
│   ├── protocol/       # WireEvent types (codegen'd from Python msgspec)
│   ├── client/         # API client (codegen'd from OpenAPI)
│   ├── transport/
│   │   ├── sse.ts
│   │   └── websocket.ts
│   ├── machines/       # chatSession, ptySession, accountWizard, onboarding
│   └── index.ts
```

- Wire protocol types codegen'd, not hand-written.
- API client codegen'd from OpenAPI via `openapi-typescript`.
- State machines hand-rolled (no XState dep), exposed as pure functions +
  reactive state containers the framework layers observe.
- No Vue/React imports anywhere.

### `packages/vue-headless` — logic-only Vue 3 composables

Wraps `ts-core` state machines in Vue reactivity. Zero markup, zero CSS.

```ts
import { useAccountWizard, useChatSession, usePtySession, useOnboarding } from '@ai-accounts/vue-headless'

const { state, backends, selectBackend, submitCredential, errors } = useAccountWizard({ client })
```

- Target bundle <10 KB gzipped.
- Depends only on `vue` (peer) and `@ai-accounts/ts-core`.

### `packages/vue-styled` — batteries-included Vue 3 components

Built on top of `vue-headless`. Opinionated markup, themeable via CSS custom
properties with an `--aia-` prefix.

Components:

- `<AiChatPanel>` — messages, input, streaming indicator, model picker
- `<AccountWizard>` — multi-step backend login wizard
- `<OnboardingFlow>` — first-run wizard container
- `<PtyTerminal>` — xterm.js terminal wired to `usePtySession`
- `<SessionList>` — live sessions with kill/resize controls
- `<ModelPicker>`, `<UsageMeter>`, `<BackendStatusBadge>`

Theming: ~40 CSS variables (colors, spacing, radii, fonts, transitions).
Defaults ship as a dark theme borrowed from Agented's Geist look;
`theme-light.css` alternative included. No Tailwind, no CSS-in-JS.

xterm.js (`@xterm/xterm` v5) is the committed terminal renderer, shipped as a
peer dep so PTY-less consumers do not pay for it.

Every component exposes slots for header/footer/empty-state/message-rendering.
Consumers who want mostly styled but custom message bubbles pass a slot
instead of dropping to headless.

### Layer relationship

```
vue-styled   ──uses──▶  vue-headless  ──uses──▶  ts-core
 (markup + CSS vars)     (composables)            (state machines + API + protocol)
```

Consumer modes:

- **Afternoon mode:** import from `@ai-accounts/vue-styled`, override a few CSS vars.
- **Brand-faithful mode:** use composables from `@ai-accounts/vue-headless`, write markup against the host design system.
- **Non-Vue mode:** use `@ai-accounts/ts-core` directly; React/Svelte/Solid layers can ship later as separate packages with the same headless/styled split.

## Extraction & migration plan

All work lands incrementally. Each phase ships a usable package version AND
deletes the corresponding Agented code. Agented-side migration happens on a
**dedicated git worktree branch** off Agented's `main`; nothing lands on
`main` until a phase is verified green.

### Phase 0 — Scaffold (~1 week)

- Create `ai-accounts` repo; `uv` + `pnpm` workspaces; CI matrix; Vitepress shell; changesets.
- Define `core/protocols/` signatures only.
- Define `core/domain/` msgspec structs.
- Define `core/protocol/` WireEvent schemas + msgspec→TS codegen pipeline.
- Stub Litestar app with `/health`.
- Stub `ts-core` package with codegen wired.
- Ships: nothing usable. Phase exists to lock interfaces.

### Phase 1 — Accounts & vault (~2 weeks)

- Implement `AccountService`, `SqliteStorage` (accounts + credentials), `EnvKeyVault`.
- Implement `BackendProtocol` for Claude and OpenCode (smallest surface that proves the abstraction).
- Litestar routes: `/api/v1/backends` CRUD + detect + validate.
- `ts-core` accounts client; `useAccountWizard`; `<AccountWizard>`.
- Ships: `ai-accounts@0.1.0`.
- Agented migration: mount Litestar app at `/api/v1/` alongside Flask routes; swap `AccountWizard.vue` for `<AccountWizard>`; delete Agented's backend CRUD and `AccountWizard.vue`.

### Phase 2 — Onboarding + remaining backends (~1 week)

- Port remaining built-in backends (Gemini, Codex, any others Agented supports).
- `OnboardingService` + state machine; onboarding routes; `useOnboarding`; `<OnboardingFlow>`.
- Ships: `ai-accounts@0.2.0`.
- Agented migration: delete Agented onboarding code; swap welcome/setup views for `<OnboardingFlow>`.

### Phase 3 — Chat (~2 weeks)

- `ChatService` orchestration; SSE transport; `cliproxy` subprocess management inside backend implementations.
- Chat history persistence.
- `CostService` + `ModelDiscoveryService` (coupled to chat, land together).
- `ts-core` chat state machine; `useChatSession`; `<AiChatPanel>`.
- Ships: `ai-accounts@0.3.0`.
- Agented migration: delete `AiChatPanel.vue`, `cliproxy_*`, `chat_state_service`, `conversation_streaming` routes.

### Phase 4 — PTY & sessions (~2 weeks, likely +50%)

- `PtyService`; WebSocket transport; subprocess signal handling; resize; cleanup on disconnect.
- `SessionService` unified tracker; limits; cleanup.
- `<PtyTerminal>` with xterm.js; `<SessionList>`.
- Ships: `ai-accounts@0.4.0` (may ship as "PTY beta" if hard issues surface).
- Agented migration: delete `pty_service.py` and session components.
- **Risk:** PTY lifecycle and disconnect/reconnect semantics are where most
  existing Agented PTY warts live. Expect slippage; ship `0.4.0` as beta
  rather than blocking the release if needed.

### Phase 5 — Auth & vault hardening (~1 week)

- Real `ApiKeyAuth` (constant-time comparison, rate limiting).
- `@ai-accounts/oidc` optional subpackage (generic OIDC provider).
- Production-mode startup guard fully enforced.
- Ships: `ai-accounts@0.5.0` — first version safe for non-localhost deployment.

### Phase 6 — 1.0 prep (~1–2 weeks)

- Vitepress docs pass: getting started, plugin guides, adapter tutorials, theming, API reference.
- Freeze `BackendProtocolV1`; commit to additive-only changes.
- Optional adapters: `@ai-accounts/sqlalchemy`, `@ai-accounts/keychain` ship in 1.0 if time permits, else 1.1.
- Ships: `ai-accounts@1.0.0` — API stability commitment, migration guide from 0.x.

**Total estimate:** 9–11 weeks focused work. Realistically double with
interruptions.

**Dogfooding invariant:** at the end of every phase, Agented is running the
package in production, and the package has a real user (Agented itself). No
phase ships speculative APIs.

## Testing strategy

Four tiers.

### Tier 1 — Protocol-level unit tests

- Every service in `core/services/` tested against in-memory fake Protocol implementations.
- `FakeStorage`, `FakeVault`, `FakeBackend`, `FakeAuth` live in `core/testing/` and are exported for consumers to reuse when testing their own adapters.
- Target: 100% service-logic coverage, sub-second runtime.

### Tier 2 — Adapter conformance suites

- Each adapter runs a shared pytest module asserting Protocol contract conformance.
- Example: `storage_conformance.py` has ~30 tests any `StorageProtocol` implementation must pass (CRUD, transactions, idempotency, race conditions, migration behavior).
- The aiosqlite and SQLAlchemy storage adapters run the identical suite in CI.
- This is what makes Protocol boundaries trustworthy for third-party adapter authors.

### Tier 3 — Integration tests against live subprocesses

- Backend adapters tested against real CLIs, marked `@pytest.mark.integration`, gated on CLI installation.
- Recorded cassettes for common cases; real-subprocess runs on nightly CI or manual trigger.
- PTY tests use `ptyprocess` against `cat`/`bash` harnesses separate from backend tests.

### Tier 4 — End-to-end against Litestar app

- `httpx.AsyncClient` in-process (no network).
- Litestar test client for SSE and WebSocket flows.
- Production-mode startup guard has explicit tests.

### Frontend testing

- `ts-core` state machines: Vitest.
- `vue-headless` composables: `@vue/test-utils` + Vitest.
- `vue-styled` components: Playwright visual regression on the playground app.
- Codegen verification: CI fails if msgspec→TS or OpenAPI→TS regeneration produces a diff against committed files.

### Cross-cutting

- Property-based tests (Hypothesis) for wire protocol encoder/decoder round-trip.
- `tox`/`nox` command runs the full matrix locally; CI mirrors it.
- Coverage targets: 90% core, 80% litestar, 70% vue-styled. Tier 3 not counted.

### Explicitly out of scope

No contract tests between Agented and the package live inside the package
repo. Agented dogfoods at runtime; that is a separate, lower ceremony form of
integration testing.

## Tooling, versioning, release

### Build

- Python: `uv` (install, lock, workspaces, publish). One `uv.lock` at repo root.
- JavaScript: `pnpm` workspaces. One `pnpm-lock.yaml` at repo root. `tsup` for package builds (ESM + CJS + `.d.ts`).
- Top-level `justfile` dispatches cross-language commands: `just test`, `just build`, `just docs`, `just release`, `just codegen`.
- Codegen runs in CI with a `git diff --exit-code` gate.

### CI (GitHub Actions)

- Matrix: Python 3.11, 3.12 × Node 20, 22 × Ubuntu + macOS (Windows best-effort).
- Jobs: lint (ruff + eslint), typecheck (mypy + tsc), Tier 1+2+4 tests, docs build, codegen verification.
- Nightly: Tier 3 integration tests.
- Required for merge: lint, typecheck, unit tests, codegen check on at least one Python × Node combo.

### Versioning

- Changesets for release management.
- Python packages bump via changesets + a small custom script that updates `pyproject.toml` versions.
- Lockstep versioning during 0.x: any package bump bumps everything. Post-1.0 may split streams.
- Wire protocol has its own version field; independent of package version.

### Semver

- 0.x: anything can break between minor versions; documented in changelogs. Covers Phases 1–5 of the migration plan.
- 1.0+: strict semver. `BackendProtocol`, `StorageProtocol`, `VaultProtocol`, `AuthProtocol` frozen as V1; additive changes only within a major.

### Publishing

- Python to PyPI via `uv publish`. JS to npm via `pnpm publish`. Release PR merge triggers both in a single workflow.

### Documentation

- Vitepress site deployed to GitHub Pages from `main`, preview deploys for PRs.
- Sections: getting started, concepts (Protocols, adapters, theming, wire protocol), recipes (custom backend, custom storage, OIDC wiring, theming), API reference (auto-generated from docstrings and TSDoc).

### Governance (lightweight)

- `CONTRIBUTING.md` explains Protocol + adapter pattern; "don't add logic to Litestar routes, put it in core services."
- `CODE_OF_CONDUCT.md` Contributor Covenant.
- Issue templates: bug, feature, adapter proposal.
- No formal governance for v1; single maintainer until that stops working.

### Security

- `SECURITY.md` with disclosure contact and scope (in: vault encryption, auth bypass, credential leakage; out: dev-mode warnings, localhost defaults).
- Dependabot; `pip-audit`; `npm audit` in CI.

### License

Apache-2.0. Explicit patent grant matters for a package that talks to
commercial AI APIs.

## Open items to resolve during implementation

- Exact list of AI backends to ship in v1 beyond Claude, OpenCode, Gemini, Codex.
- Naming: `ai-accounts` is a working title. Final name chosen before `0.1.0` publish.
- Whether to ship msgpack or JSON over WebSocket for PTY. Msgpack is smaller; JSON is debuggable. Default proposed: JSON until profiling shows a reason to change.
- Exact CSS variable set for `vue-styled`. Target ~40; final list settles during Phase 1 component work.

## Risks

- **PTY lifecycle complexity** — Phase 4 is the most likely to slip. Beta ship is acceptable.
- **Codegen drift** — if msgspec→TS or OpenAPI→TS codegen breaks, the entire client/server contract breaks. Mitigated by the CI diff gate.
- **Protocol churn during 0.x** — consumers who adopt pre-1.0 will feel breaking changes. Documented clearly in CHANGELOG; migration notes per minor version.
- **Agented migration friction** — the Flask + ASGI bridge during Phase 1–5 is temporary but ugly. If it blocks progress, fallback is to proxy Flask and Litestar on separate ports at the frontend dev server.
- **Single maintainer** — no bus-factor plan in v1. Governance revisits post-1.0.
