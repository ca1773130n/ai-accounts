# ai-accounts

Reusable account management, login orchestration, chat, and PTY session package
for AI CLI backends — **Claude**, **Codex**, **Gemini**, **OpenCode**.

Python ([Litestar](https://litestar.dev)) sidecar API + TypeScript / Vue 3
client packages. Apache-2.0.

**Latest release: `0.3.9`** ([CHANGELOG](./CHANGELOG.md))

---

## What this is

Many AI CLI tools (`claude`, `codex`, `gemini`, `opencode`) authenticate via OAuth
and store credentials in per-tool config dirs or the system Keychain. Wiring one
account works; juggling several across multiple backends, isolating their config
dirs, and routing chat/PTY traffic through a unified API gets fiddly fast.

`ai-accounts` is the layer that does it for you:

- **Per-account isolation**: each account gets its own `CLAUDE_CONFIG_DIR` /
  `CODEX_HOME` / etc., so multiple Codex accounts (for example) don't clobber
  each other.
- **Onboarding wizard**: a Vue component drives the whole add-account flow —
  CLI install check, OAuth/device-code, eager paste-code, optional
  [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) registration.
- **Smart chat panel**: single backend, fan-out to all backends, or
  compound-mode synthesis through a primary backend. Live streaming, tool-call
  process groups, tokens-in/out tracking, and per-backend account labels.
- **PTY sessions** over WebSocket for interactive CLI work.
- **Live model discovery** from CLIProxyAPI when registered, with static
  fallbacks per backend so the dropdown is never empty.
- **Pluggable adapters** for storage (sqlite/sqlalchemy), vault
  (env-key AES-GCM, KMS, vault, keychain), and auth (none/api-key/OIDC).

---

## Packages

| Package                              | Kind | npm / PyPI                                                              |
| ------------------------------------ | ---- | ----------------------------------------------------------------------- |
| `ai-accounts-core`                   | Py   | workspace (depends from `ai-accounts-litestar`)                         |
| `ai-accounts-litestar`               | Py   | workspace                                                               |
| `@ai-accounts/ts-core`               | TS   | [npm](https://www.npmjs.com/package/@ai-accounts/ts-core)               |
| `@ai-accounts/vue-headless`          | TS   | [npm](https://www.npmjs.com/package/@ai-accounts/vue-headless)          |
| `@ai-accounts/vue-styled`            | TS   | [npm](https://www.npmjs.com/package/@ai-accounts/vue-styled)            |
| `apps/playground`                    | App  | private — local-dev showcase                                            |

---

## Quickstart — playground

The playground app is the fastest way to try the wizard, account list, remove
button, and chat panel against real CLI accounts.

```bash
git clone https://github.com/ca1773130n/ai-accounts.git
cd ai-accounts

# Sets up Python (uv) + JS (pnpm) workspaces.
just setup

# Start both: Python sidecar API on :30000, Vite dev server on :6173.
pnpm --filter playground start

# Open http://localhost:6173/
```

Override the API host/port with env vars:

```bash
AIA_HOST=0.0.0.0 AIA_PORT=8080 pnpm --filter playground server
```

---

## Use as a library — JS

```ts
import { AiAccountsClient } from '@ai-accounts/ts-core'
import { AccountWizard, AiChatPanel } from '@ai-accounts/vue-styled'
import { aiAccountsPlugin } from '@ai-accounts/vue-headless'
import '@ai-accounts/vue-styled/styles.css'

const client = new AiAccountsClient({ baseUrl: 'http://localhost:30000' })
app.use(aiAccountsPlugin, { client })

// then in a component:
// <AccountWizard @done="onAccountAdded" />
// <AiChatPanel density="detailed" />
```

---

## Use as a library — Python

```python
from ai_accounts_core.adapters.auth_apikey import ApiKeyAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.backends import (
    ClaudeBackend, CodexBackend, GeminiBackend, OpenCodeBackend,
)
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig

app = create_app(AiAccountsConfig(
    env="production",
    storage=SqliteStorage("./accounts.db"),
    vault=EnvKeyVault.from_env(env="production"),  # AI_ACCOUNTS_VAULT_KEY
    auth=ApiKeyAuth(keys={"sk-..."}),
    backends=(ClaudeBackend(), CodexBackend(), GeminiBackend(), OpenCodeBackend()),
))
```

---

## Development — `just` recipes

```bash
just setup        # uv sync + pnpm install
just test         # both Python + JS test suites
just test-py      # Python only
just test-js      # JS only
just lint         # ruff check + format check + pnpm -r lint
just format       # ruff format + ruff fix
just typecheck    # mypy + vue-tsc
just build        # pnpm -r build
just codegen      # regen wire types + OpenAPI

# Release
just bump 0.4.0   # version bump in lockstep across all packages
just release 0.4.0  # tag, push, npm publish — refuses dirty tree / non-main
```

---

## Architecture

See [`docs/superpowers/ARCHITECTURE.md`](./docs/superpowers/ARCHITECTURE.md) for
the package dependency graph, layer protocols, and data flow.

See [`docs/superpowers/MAINTENANCE.md`](./docs/superpowers/MAINTENANCE.md) for
operational knowledge — dependency inventory, upgrade paths, schema migrations,
release process.

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md). Issues and PRs welcome.

## License

Apache-2.0. See [`LICENSE`](./LICENSE).
