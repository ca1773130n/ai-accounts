# ai-accounts Phase 0 + Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the `ai-accounts` monorepo (Phase 0) and ship `ai-accounts@0.1.0` — a working AI backend account manager with Claude + OpenCode backends, Litestar HTTP API, TS/Vue frontend, and a live demo in Agented (Phase 1).

**Architecture:** Python `core` package with Protocol-based architecture (Storage, Vault, Auth, Backend, Transport), default adapters (aiosqlite + AES-GCM env-key vault), Litestar HTTP layer, TypeScript `ts-core` + Vue 3 headless + Vue 3 styled frontend layers. Agented dogfoods the package via ASGI-mount alongside its existing Flask app on a dedicated worktree branch.

**Tech Stack:** Python 3.11+, Litestar 2.x, msgspec, aiosqlite, cryptography (AES-GCM), `uv` workspaces. TypeScript 5.x, Vue 3, Vitest, `pnpm` workspaces, `tsup`. Vitepress docs. Changesets. Apache-2.0.

**Scope boundary:** This plan covers Phase 0 (scaffolding) and Phase 1 (accounts & vault). Phases 2-6 (onboarding, chat, PTY, auth hardening, 1.0 prep) will be planned separately once Phase 1 ships.

**Spec reference:** `docs/superpowers/specs/2026-04-11-ai-accounts-package-design.md`

**Prerequisite check — run BEFORE Task 1:**
```bash
python3.11 --version   # expect 3.11+
node --version         # expect v20+
pnpm --version         # expect 9+
uv --version           # expect 0.5+
just --version         # expect 1.30+
```
If any are missing, install them before starting. On macOS: `brew install python@3.11 node pnpm uv just`.

---

## Plan structure

- **Part A — Phase 0: Scaffolding** (Tasks 1–12): repo, workspaces, CI, docs, protocols, domain, wire codegen, Litestar stub, ts-core stub.
- **Part B — Phase 1: Accounts & Vault** (Tasks 13–40): SQLite storage, AES-GCM vault, auth stubs, AccountService, Claude + OpenCode backends, Litestar routes, ts-core client, vue-headless, vue-styled, playground.
- **Part C — Agented integration** (Tasks 41–48): worktree setup, ASGI mount, component swap, old code deletion, 0.1.0 release dry run.

---

# Part A — Phase 0: Scaffolding

## Task 1: Create repo skeleton and license

**Files:**
- Create: `~/Developer/Projects/ai-accounts/` (new directory)
- Create: `~/Developer/Projects/ai-accounts/LICENSE`
- Create: `~/Developer/Projects/ai-accounts/README.md`
- Create: `~/Developer/Projects/ai-accounts/.gitignore`
- Create: `~/Developer/Projects/ai-accounts/CODE_OF_CONDUCT.md`
- Create: `~/Developer/Projects/ai-accounts/CONTRIBUTING.md`
- Create: `~/Developer/Projects/ai-accounts/SECURITY.md`

- [ ] **Step 1: Create directory and initialize git**

```bash
mkdir -p ~/Developer/Projects/ai-accounts
cd ~/Developer/Projects/ai-accounts
git init -b main
```

- [ ] **Step 2: Write LICENSE (Apache-2.0)**

Fetch the canonical Apache-2.0 text:
```bash
curl -sSL https://www.apache.org/licenses/LICENSE-2.0.txt > LICENSE
```

Verify: `head -1 LICENSE` → `Apache License`

- [ ] **Step 3: Write .gitignore**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/

# Node
node_modules/
pnpm-debug.log*
.turbo/
*.tsbuildinfo

# Editor / OS
.DS_Store
.idea/
.vscode/
*.swp

# Secrets / local state
.env
.env.local
*.db
accounts.db
```

- [ ] **Step 4: Write minimal README.md**

```markdown
# ai-accounts

Reusable AI backend account management, onboarding, chat, and PTY session package. Python (Litestar) backend + TypeScript/Vue frontend. Apache-2.0.

**Status:** Early development. Not yet released.

See `docs/` for design spec and implementation plan.
```

- [ ] **Step 5: Write CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md stubs**

`CODE_OF_CONDUCT.md`: fetch Contributor Covenant 2.1:
```bash
curl -sSL https://www.contributor-covenant.org/version/2/1/code_of_conduct.txt > CODE_OF_CONDUCT.md
```

`CONTRIBUTING.md`:
```markdown
# Contributing to ai-accounts

## Architecture rule

**Logic lives in `packages/core/services/`. Routes in `packages/litestar/` must be thin.**

If you find yourself writing business logic inside a Litestar route handler, stop: move it to a service in `core`, take dependencies via `Protocol`, add a unit test against a fake.

## Adding a new adapter

Every adapter (storage, vault, auth, backend) must:
1. Implement the relevant `Protocol` from `packages/core/protocols/`.
2. Pass the shared conformance suite in `packages/core/testing/<kind>_conformance.py`.
3. Ship as its own workspace package under `packages/` if it introduces dependencies beyond `core`.

## Dev setup

```bash
just setup    # installs Python + JS deps
just test     # runs full matrix
just codegen  # regenerates TS types from Python schemas + OpenAPI
```

Commit codegen output alongside the source change.
```

`SECURITY.md`:
```markdown
# Security Policy

## Reporting

Email <security@ai-accounts.dev> (placeholder — will be replaced before 0.1.0 publish). Do not open public issues for suspected vulnerabilities.

## In scope

- Vault encryption/decryption correctness
- Auth bypass in `AuthProtocol` implementations shipped by this package
- Credential leakage via logs, error messages, or API responses
- SSRF or injection in backend detection

## Out of scope

- Dev-mode warnings being present (they are intentional)
- Localhost defaults being insecure (they are intentional for dev)
- Third-party AI CLI vulnerabilities (report to the CLI vendor)
```

- [ ] **Step 6: Initial commit**

```bash
cd ~/Developer/Projects/ai-accounts
git add LICENSE README.md .gitignore CODE_OF_CONDUCT.md CONTRIBUTING.md SECURITY.md
git commit -m "chore: initial commit with license, readme, and community files"
```

---

## Task 2: Python workspace (`uv`)

**Files:**
- Create: `pyproject.toml` (workspace root)
- Create: `packages/core/pyproject.toml`
- Create: `packages/core/src/ai_accounts_core/__init__.py`
- Create: `packages/litestar/pyproject.toml`
- Create: `packages/litestar/src/ai_accounts_litestar/__init__.py`

- [ ] **Step 1: Write workspace root `pyproject.toml`**

```toml
[project]
name = "ai-accounts-workspace"
version = "0.0.0"
description = "ai-accounts monorepo workspace root (not published)"
requires-python = ">=3.11"

[tool.uv.workspace]
members = ["packages/core", "packages/litestar"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "hypothesis>=6.100",
    "mypy>=1.11",
    "ruff>=0.6",
    "httpx>=0.27",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "A", "C4", "SIM", "RET", "ASYNC"]
ignore = ["E501"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["packages/*/tests"]

[tool.mypy]
python_version = "3.11"
strict = true
```

- [ ] **Step 2: Write `packages/core/pyproject.toml`**

```toml
[project]
name = "ai-accounts-core"
version = "0.0.0"
description = "Framework-agnostic core for ai-accounts: protocols, services, wire protocol."
readme = "README.md"
license = {text = "Apache-2.0"}
requires-python = ">=3.11"
dependencies = [
    "msgspec>=0.18",
    "aiosqlite>=0.20",
    "cryptography>=43.0",
]

[project.optional-dependencies]
testing = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ai_accounts_core"]
```

- [ ] **Step 3: Write `packages/core/src/ai_accounts_core/__init__.py`**

```python
"""Framework-agnostic core for ai-accounts."""

__version__ = "0.0.0"
```

Also: `touch packages/core/README.md` containing one line `# ai-accounts-core`.

- [ ] **Step 4: Write `packages/litestar/pyproject.toml`**

```toml
[project]
name = "ai-accounts-litestar"
version = "0.0.0"
description = "Litestar HTTP layer for ai-accounts."
readme = "README.md"
license = {text = "Apache-2.0"}
requires-python = ">=3.11"
dependencies = [
    "ai-accounts-core",
    "litestar[standard]>=2.12",
]

[tool.uv.sources]
ai-accounts-core = {workspace = true}

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ai_accounts_litestar"]
```

- [ ] **Step 5: Write `packages/litestar/src/ai_accounts_litestar/__init__.py`**

```python
"""Litestar HTTP layer for ai-accounts."""

__version__ = "0.0.0"
```

Also: `touch packages/litestar/README.md` with `# ai-accounts-litestar`.

- [ ] **Step 6: Sync workspace and verify**

```bash
cd ~/Developer/Projects/ai-accounts
uv sync
uv run python -c "import ai_accounts_core, ai_accounts_litestar; print('ok')"
```

Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml packages/core packages/litestar uv.lock
git commit -m "chore: set up Python workspace with core and litestar packages"
```

---

## Task 3: JS workspace (`pnpm`)

**Files:**
- Create: `package.json` (workspace root)
- Create: `pnpm-workspace.yaml`
- Create: `tsconfig.base.json`
- Create: `packages/ts-core/package.json`
- Create: `packages/ts-core/tsconfig.json`
- Create: `packages/ts-core/src/index.ts`
- Create: `packages/vue-headless/package.json`
- Create: `packages/vue-headless/tsconfig.json`
- Create: `packages/vue-headless/src/index.ts`
- Create: `packages/vue-styled/package.json`
- Create: `packages/vue-styled/tsconfig.json`
- Create: `packages/vue-styled/src/index.ts`

- [ ] **Step 1: Write `package.json` (workspace root)**

```json
{
  "name": "ai-accounts-workspace",
  "version": "0.0.0",
  "private": true,
  "packageManager": "pnpm@9.12.0",
  "scripts": {
    "build": "pnpm -r build",
    "test": "pnpm -r test",
    "lint": "pnpm -r lint",
    "typecheck": "pnpm -r typecheck"
  },
  "devDependencies": {
    "typescript": "^5.5.0",
    "tsup": "^8.3.0",
    "vitest": "^2.1.0",
    "@vitest/coverage-v8": "^2.1.0",
    "@types/node": "^22.0.0",
    "eslint": "^9.10.0",
    "@typescript-eslint/parser": "^8.5.0",
    "@typescript-eslint/eslint-plugin": "^8.5.0"
  }
}
```

- [ ] **Step 2: Write `pnpm-workspace.yaml`**

```yaml
packages:
  - "packages/ts-core"
  - "packages/vue-headless"
  - "packages/vue-styled"
  - "apps/*"
  - "docs"
```

- [ ] **Step 3: Write `tsconfig.base.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "isolatedModules": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "lib": ["ES2022", "DOM"]
  }
}
```

- [ ] **Step 4: Write `packages/ts-core/package.json`**

```json
{
  "name": "@ai-accounts/ts-core",
  "version": "0.0.0",
  "description": "Framework-agnostic TypeScript client and protocol for ai-accounts",
  "license": "Apache-2.0",
  "type": "module",
  "main": "./dist/index.cjs",
  "module": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "import": "./dist/index.js",
      "require": "./dist/index.cjs",
      "types": "./dist/index.d.ts"
    }
  },
  "files": ["dist"],
  "scripts": {
    "build": "tsup src/index.ts --format esm,cjs --dts --clean",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src",
    "typecheck": "tsc --noEmit"
  }
}
```

- [ ] **Step 5: Write `packages/ts-core/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src",
    "lib": ["ES2022"]
  },
  "include": ["src/**/*"]
}
```

- [ ] **Step 6: Write `packages/ts-core/src/index.ts` (stub)**

```typescript
export const version = "0.0.0";
```

- [ ] **Step 7: Write `packages/vue-headless/package.json`**

```json
{
  "name": "@ai-accounts/vue-headless",
  "version": "0.0.0",
  "description": "Vue 3 headless composables for ai-accounts",
  "license": "Apache-2.0",
  "type": "module",
  "main": "./dist/index.cjs",
  "module": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "import": "./dist/index.js",
      "require": "./dist/index.cjs",
      "types": "./dist/index.d.ts"
    }
  },
  "files": ["dist"],
  "peerDependencies": {
    "vue": "^3.4.0"
  },
  "dependencies": {
    "@ai-accounts/ts-core": "workspace:*"
  },
  "devDependencies": {
    "vue": "^3.4.0",
    "@vue/test-utils": "^2.4.0",
    "happy-dom": "^15.0.0"
  },
  "scripts": {
    "build": "tsup src/index.ts --format esm,cjs --dts --clean --external vue",
    "test": "vitest run",
    "lint": "eslint src",
    "typecheck": "tsc --noEmit"
  }
}
```

- [ ] **Step 8: Write `packages/vue-headless/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src",
    "lib": ["ES2022", "DOM"]
  },
  "include": ["src/**/*"]
}
```

- [ ] **Step 9: Write `packages/vue-headless/src/index.ts` (stub)**

```typescript
export const version = "0.0.0";
```

- [ ] **Step 10: Write `packages/vue-styled/package.json`**

```json
{
  "name": "@ai-accounts/vue-styled",
  "version": "0.0.0",
  "description": "Vue 3 styled components for ai-accounts",
  "license": "Apache-2.0",
  "type": "module",
  "main": "./dist/index.cjs",
  "module": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "import": "./dist/index.js",
      "require": "./dist/index.cjs",
      "types": "./dist/index.d.ts"
    },
    "./styles.css": "./dist/styles.css"
  },
  "files": ["dist"],
  "peerDependencies": {
    "vue": "^3.4.0"
  },
  "dependencies": {
    "@ai-accounts/ts-core": "workspace:*",
    "@ai-accounts/vue-headless": "workspace:*"
  },
  "devDependencies": {
    "vue": "^3.4.0"
  },
  "scripts": {
    "build": "tsup src/index.ts --format esm,cjs --dts --clean --external vue",
    "test": "vitest run",
    "lint": "eslint src",
    "typecheck": "tsc --noEmit"
  }
}
```

- [ ] **Step 11: Write `packages/vue-styled/tsconfig.json` (same as vue-headless)**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src",
    "lib": ["ES2022", "DOM"]
  },
  "include": ["src/**/*"]
}
```

- [ ] **Step 12: Write `packages/vue-styled/src/index.ts` (stub)**

```typescript
export const version = "0.0.0";
```

- [ ] **Step 13: Install and verify**

```bash
pnpm install
pnpm -r build
pnpm -r typecheck
```

Expected: all three packages build, typecheck passes with 0 errors.

- [ ] **Step 14: Commit**

```bash
git add package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json packages/ts-core packages/vue-headless packages/vue-styled
git commit -m "chore: set up pnpm workspace with ts-core, vue-headless, vue-styled"
```

---

## Task 4: Top-level justfile

**Files:**
- Create: `justfile`

- [ ] **Step 1: Write `justfile`**

```makefile
default:
    @just --list

setup:
    uv sync
    pnpm install

test:
    uv run pytest
    pnpm -r test

test-py:
    uv run pytest

test-js:
    pnpm -r test

lint:
    uv run ruff check .
    uv run ruff format --check .
    pnpm -r lint

format:
    uv run ruff format .
    uv run ruff check --fix .

typecheck:
    uv run mypy packages/core/src packages/litestar/src
    pnpm -r typecheck

build:
    pnpm -r build

codegen:
    uv run python scripts/codegen_wire_types.py
    uv run python scripts/codegen_openapi.py

docs-dev:
    pnpm --filter docs dev

docs-build:
    pnpm --filter docs build

clean:
    rm -rf packages/*/dist packages/*/.turbo
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
```

- [ ] **Step 2: Verify**

```bash
just
```
Expected: list of available recipes.

- [ ] **Step 3: Commit**

```bash
git add justfile
git commit -m "chore: add top-level justfile for cross-language commands"
```

---

## Task 5: CI workflow (GitHub Actions)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  python:
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.12"]
        os: [ubuntu-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv python install ${{ matrix.python }}
      - run: uv sync --all-extras
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy packages/core/src packages/litestar/src
      - run: uv run pytest -v --cov --cov-report=xml

  javascript:
    strategy:
      fail-fast: false
      matrix:
        node: ["20", "22"]
        os: [ubuntu-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 9
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm -r typecheck
      - run: pnpm -r lint
      - run: pnpm -r build
      - run: pnpm -r test

  codegen:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - uses: pnpm/action-setup@v4
        with:
          version: 9
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: pnpm
      - run: uv sync
      - run: pnpm install --frozen-lockfile
      - run: just codegen
      - name: Fail if codegen produced a diff
        run: git diff --exit-code
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add Python + JS matrix + codegen verification workflow"
```

---

## Task 6: Changesets setup

**Files:**
- Create: `.changeset/config.json`
- Create: `.changeset/README.md`

- [ ] **Step 1: Install changesets**

```bash
cd ~/Developer/Projects/ai-accounts
pnpm add -Dw @changesets/cli
pnpm changeset init
```

This creates `.changeset/config.json` and `.changeset/README.md`.

- [ ] **Step 2: Edit `.changeset/config.json` for lockstep versioning**

```json
{
  "$schema": "https://unpkg.com/@changesets/config@3.0.0/schema.json",
  "changelog": "@changesets/cli/changelog",
  "commit": false,
  "fixed": [["@ai-accounts/ts-core", "@ai-accounts/vue-headless", "@ai-accounts/vue-styled"]],
  "linked": [],
  "access": "public",
  "baseBranch": "main",
  "updateInternalDependencies": "patch",
  "ignore": []
}
```

Note: Python packages are not managed by changesets directly. We'll handle them with a custom script in Task 9.

- [ ] **Step 3: Commit**

```bash
git add .changeset package.json pnpm-lock.yaml
git commit -m "chore: set up changesets with fixed versioning for JS packages"
```

---

## Task 7: Vitepress docs shell

**Files:**
- Create: `docs/package.json`
- Create: `docs/.vitepress/config.ts`
- Create: `docs/index.md`
- Create: `docs/guide/getting-started.md`
- Create: `docs/concepts/architecture.md`

- [ ] **Step 1: Write `docs/package.json`**

```json
{
  "name": "docs",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "dev": "vitepress dev",
    "build": "vitepress build",
    "preview": "vitepress preview"
  },
  "devDependencies": {
    "vitepress": "^1.4.0",
    "vue": "^3.4.0"
  }
}
```

- [ ] **Step 2: Write `docs/.vitepress/config.ts`**

```typescript
import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'ai-accounts',
  description: 'Reusable AI backend, chat, and PTY session package',
  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'Concepts', link: '/concepts/architecture' },
    ],
    sidebar: {
      '/guide/': [
        { text: 'Getting Started', link: '/guide/getting-started' },
      ],
      '/concepts/': [
        { text: 'Architecture', link: '/concepts/architecture' },
      ],
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/ca1773130n/ai-accounts' },
    ],
  },
});
```

- [ ] **Step 3: Write `docs/index.md`**

```markdown
---
layout: home
hero:
  name: ai-accounts
  text: AI backends, chat, and PTY sessions
  tagline: A reusable, framework-agnostic package for any project that needs to manage AI CLI backends
features:
  - title: Protocol-first
    details: Small, typed interfaces for storage, vault, auth, and backends. Swap any layer.
  - title: Batteries included
    details: Ships with SQLite, AES-GCM vault, Claude and OpenCode backends, and themeable Vue components.
  - title: Embeddable
    details: Use the HTTP API, or import services directly for in-process use in CLIs and desktop apps.
---
```

- [ ] **Step 4: Write `docs/guide/getting-started.md`**

```markdown
# Getting Started

> Placeholder — will be filled in as `ai-accounts@0.1.0` nears release.

## Install

```bash
pip install ai-accounts-core ai-accounts-litestar
pnpm add @ai-accounts/ts-core @ai-accounts/vue-styled
```

## Minimum app

Coming soon.
```

- [ ] **Step 5: Write `docs/concepts/architecture.md`**

Copy the "Architectural spine" section from `docs/superpowers/specs/2026-04-11-ai-accounts-package-design.md` (the Protocol + default adapter + optional adapters table).

- [ ] **Step 6: Verify build**

```bash
cd ~/Developer/Projects/ai-accounts
pnpm install
pnpm --filter docs build
```

Expected: build succeeds, output in `docs/.vitepress/dist/`.

- [ ] **Step 7: Commit**

```bash
git add docs/ pnpm-lock.yaml
git commit -m "docs: add Vitepress shell with getting-started and architecture pages"
```

---

## Task 8: Core domain models

**Files:**
- Create: `packages/core/src/ai_accounts_core/domain/__init__.py`
- Create: `packages/core/src/ai_accounts_core/domain/backend.py`
- Create: `packages/core/src/ai_accounts_core/domain/chat.py`
- Create: `packages/core/src/ai_accounts_core/domain/pty.py`
- Create: `packages/core/src/ai_accounts_core/domain/session.py`
- Create: `packages/core/src/ai_accounts_core/domain/onboarding.py`
- Create: `packages/core/src/ai_accounts_core/domain/principal.py`
- Create: `packages/core/tests/test_domain.py`

- [ ] **Step 1: Write the failing test `packages/core/tests/test_domain.py`**

```python
from datetime import UTC, datetime

from ai_accounts_core.domain.backend import Backend, BackendCredential, BackendKind, BackendStatus
from ai_accounts_core.domain.chat import ChatMessage, ChatRole, ChatSession
from ai_accounts_core.domain.principal import Principal


def test_backend_construction():
    backend = Backend(
        id="bkd-abc123",
        kind=BackendKind.CLAUDE,
        display_name="Claude main",
        config={},
        status=BackendStatus.READY,
        created_at=datetime.now(UTC),
    )
    assert backend.id == "bkd-abc123"
    assert backend.kind is BackendKind.CLAUDE
    assert backend.status is BackendStatus.READY


def test_backend_credential_never_exposes_plaintext():
    cred = BackendCredential(
        id="crd-xyz789",
        backend_id="bkd-abc123",
        ciphertext=b"\x01\x02\x03",
        key_id="kms://local/v1",
        created_at=datetime.now(UTC),
    )
    assert cred.ciphertext == b"\x01\x02\x03"
    # BackendCredential MUST NOT carry a plaintext field
    assert not hasattr(cred, "plaintext")


def test_chat_message_roles():
    msg = ChatMessage(
        id="msg-1",
        session_id="sess-1",
        role=ChatRole.USER,
        content="hello",
        created_at=datetime.now(UTC),
    )
    assert msg.role is ChatRole.USER


def test_principal_identifies_caller():
    p = Principal(id="user:local", display_name="Local Dev", scopes=frozenset({"read", "write"}))
    assert "read" in p.scopes
```

- [ ] **Step 2: Run test — expect import failure**

```bash
cd ~/Developer/Projects/ai-accounts
uv run pytest packages/core/tests/test_domain.py -v
```
Expected: `ModuleNotFoundError: ai_accounts_core.domain.backend`

- [ ] **Step 3: Write `domain/__init__.py`**

```python
"""Domain types — framework-free msgspec structs."""
```

- [ ] **Step 4: Write `domain/backend.py`**

```python
from datetime import datetime
from enum import Enum

import msgspec


class BackendKind(str, Enum):
    CLAUDE = "claude"
    OPENCODE = "opencode"
    GEMINI = "gemini"
    CODEX = "codex"


class BackendStatus(str, Enum):
    UNCONFIGURED = "unconfigured"
    DETECTING = "detecting"
    NEEDS_LOGIN = "needs_login"
    VALIDATING = "validating"
    READY = "ready"
    ERROR = "error"


class Backend(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    kind: BackendKind
    display_name: str
    config: dict
    status: BackendStatus
    created_at: datetime
    updated_at: datetime | None = None
    last_error: str | None = None


class BackendCredential(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    backend_id: str
    ciphertext: bytes
    key_id: str
    created_at: datetime
    expires_at: datetime | None = None


class DetectResult(msgspec.Struct, frozen=True, kw_only=True):
    installed: bool
    version: str | None = None
    path: str | None = None
    notes: str | None = None
```

- [ ] **Step 5: Write `domain/chat.py`**

```python
from datetime import datetime
from enum import Enum

import msgspec


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    session_id: str
    role: ChatRole
    content: str
    created_at: datetime
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


class ChatSession(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    backend_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime | None = None
    model: str | None = None
```

- [ ] **Step 6: Write `domain/pty.py`**

```python
from datetime import datetime

import msgspec


class PtySession(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    backend_id: str
    command: tuple[str, ...]
    cols: int
    rows: int
    created_at: datetime
    ended_at: datetime | None = None
    exit_code: int | None = None


class PtyEvent(msgspec.Struct, frozen=True, kw_only=True):
    session_id: str
    kind: str  # "output" | "resize" | "exit" | "input"
    payload: bytes
    ts: datetime
```

- [ ] **Step 7: Write `domain/session.py`**

```python
from datetime import datetime
from enum import Enum

import msgspec


class SessionKind(str, Enum):
    CHAT = "chat"
    PTY = "pty"


class SessionState(str, Enum):
    STARTING = "starting"
    ACTIVE = "active"
    DISCONNECTED = "disconnected"
    ENDED = "ended"
    ERRORED = "errored"


class LiveSession(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    kind: SessionKind
    backend_id: str
    state: SessionState
    started_at: datetime
    last_seen_at: datetime
```

- [ ] **Step 8: Write `domain/onboarding.py`**

```python
from enum import Enum

import msgspec


class OnboardingStep(str, Enum):
    WELCOME = "welcome"
    DETECT = "detect"
    PICK_BACKEND = "pick_backend"
    LOGIN = "login"
    VALIDATE = "validate"
    DONE = "done"


class OnboardingState(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    current_step: OnboardingStep
    selected_backend_kind: str | None = None
    created_backend_id: str | None = None
    error: str | None = None
```

- [ ] **Step 9: Write `domain/principal.py`**

```python
import msgspec


class Principal(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    display_name: str
    scopes: frozenset[str] = frozenset()
```

- [ ] **Step 10: Run tests — expect pass**

```bash
uv run pytest packages/core/tests/test_domain.py -v
```
Expected: 4 tests pass.

- [ ] **Step 11: Commit**

```bash
git add packages/core/src/ai_accounts_core/domain packages/core/tests/test_domain.py
git commit -m "feat(core): add domain models (Backend, Credential, Chat, PTY, Session, Principal)"
```

---

## Task 9: Core Protocols

**Files:**
- Create: `packages/core/src/ai_accounts_core/protocols/__init__.py`
- Create: `packages/core/src/ai_accounts_core/protocols/storage.py`
- Create: `packages/core/src/ai_accounts_core/protocols/vault.py`
- Create: `packages/core/src/ai_accounts_core/protocols/auth.py`
- Create: `packages/core/src/ai_accounts_core/protocols/backend.py`
- Create: `packages/core/src/ai_accounts_core/protocols/transport.py`
- Create: `packages/core/tests/test_protocols.py`

- [ ] **Step 1: Write failing test `packages/core/tests/test_protocols.py`**

```python
"""Smoke tests that protocol modules import and expose expected symbols."""

from ai_accounts_core.protocols import storage, vault, auth, backend, transport


def test_storage_protocol_exports():
    assert hasattr(storage, "StorageProtocol")
    assert hasattr(storage, "BackendRepository")
    assert hasattr(storage, "SessionRepository")
    assert hasattr(storage, "HistoryRepository")
    assert hasattr(storage, "OnboardingRepository")


def test_vault_protocol_exports():
    assert hasattr(vault, "VaultProtocol")
    assert hasattr(vault, "VaultError")


def test_auth_protocol_exports():
    assert hasattr(auth, "AuthProtocol")
    assert hasattr(auth, "RequestContext")


def test_backend_protocol_exports():
    assert hasattr(backend, "BackendProtocol")
    assert hasattr(backend, "LoginFlow")
    assert hasattr(backend, "ChatRequest")
    assert hasattr(backend, "PtyRequest")


def test_transport_protocol_exports():
    assert hasattr(transport, "TransportProtocol")
```

- [ ] **Step 2: Run — expect import error**

```bash
uv run pytest packages/core/tests/test_protocols.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Write `protocols/__init__.py`**

```python
"""Typed Protocol interfaces for pluggable layers."""
```

- [ ] **Step 4: Write `protocols/storage.py`**

```python
from typing import Protocol, runtime_checkable

from ai_accounts_core.domain.backend import Backend, BackendCredential
from ai_accounts_core.domain.chat import ChatMessage, ChatSession
from ai_accounts_core.domain.onboarding import OnboardingState
from ai_accounts_core.domain.session import LiveSession


@runtime_checkable
class BackendRepository(Protocol):
    async def create(self, backend: Backend) -> None: ...
    async def get(self, backend_id: str) -> Backend | None: ...
    async def list(self) -> list[Backend]: ...
    async def update(self, backend: Backend) -> None: ...
    async def delete(self, backend_id: str) -> None: ...

    async def put_credential(self, credential: BackendCredential) -> None: ...
    async def get_credential(self, backend_id: str) -> BackendCredential | None: ...
    async def delete_credential(self, backend_id: str) -> None: ...


@runtime_checkable
class SessionRepository(Protocol):
    async def upsert(self, session: LiveSession) -> None: ...
    async def get(self, session_id: str) -> LiveSession | None: ...
    async def list_active(self) -> list[LiveSession]: ...
    async def end(self, session_id: str) -> None: ...


@runtime_checkable
class HistoryRepository(Protocol):
    async def create_session(self, session: ChatSession) -> None: ...
    async def append_message(self, message: ChatMessage) -> None: ...
    async def list_messages(self, session_id: str) -> list[ChatMessage]: ...
    async def list_sessions(self, backend_id: str | None = None) -> list[ChatSession]: ...


@runtime_checkable
class OnboardingRepository(Protocol):
    async def get(self, onboarding_id: str) -> OnboardingState | None: ...
    async def put(self, state: OnboardingState) -> None: ...


@runtime_checkable
class StorageProtocol(Protocol):
    async def backends(self) -> BackendRepository: ...
    async def sessions(self) -> SessionRepository: ...
    async def history(self) -> HistoryRepository: ...
    async def onboarding(self) -> OnboardingRepository: ...
    async def migrate(self) -> None: ...
    async def close(self) -> None: ...
```

- [ ] **Step 5: Write `protocols/vault.py`**

```python
from typing import Protocol, runtime_checkable


class VaultError(Exception):
    """Raised when a vault operation fails (key missing, tamper, etc.)."""


@runtime_checkable
class VaultProtocol(Protocol):
    async def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> bytes: ...
    async def decrypt(self, ciphertext: bytes, *, context: dict[str, str]) -> bytes: ...
    async def current_key_id(self) -> str: ...
    async def rotate(self, old_key_id: str) -> None: ...
```

- [ ] **Step 6: Write `protocols/auth.py`**

```python
from typing import Any, Protocol, runtime_checkable

import msgspec

from ai_accounts_core.domain.principal import Principal


class RequestContext(msgspec.Struct, frozen=True, kw_only=True):
    method: str
    path: str
    headers: dict[str, str]
    query: dict[str, str] = {}
    extras: dict[str, Any] = {}


@runtime_checkable
class AuthProtocol(Protocol):
    async def authenticate(self, request: RequestContext) -> Principal | None: ...
```

- [ ] **Step 7: Write `protocols/backend.py`**

```python
from collections.abc import AsyncIterator
from typing import ClassVar, Protocol, runtime_checkable

import msgspec

from ai_accounts_core.domain.backend import Backend, BackendCredential, DetectResult
from ai_accounts_core.domain.chat import ChatMessage


class Model(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    display_name: str
    context_window: int | None = None
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None


class LoginFlow(msgspec.Struct, frozen=True, kw_only=True):
    kind: str  # "api_key" | "oauth_device" | "cli_login" | "headless"
    inputs: dict[str, str] = {}


class ChatRequest(msgspec.Struct, frozen=True, kw_only=True):
    messages: tuple[ChatMessage, ...]
    model: str
    params: dict[str, object] = {}


class PtyRequest(msgspec.Struct, frozen=True, kw_only=True):
    command: tuple[str, ...]
    cols: int
    rows: int
    env: dict[str, str] = {}


class ChatStreamEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str  # "token" | "tool_call" | "done" | "error"
    payload: object = None


class PtyHandle(Protocol):
    async def write(self, data: bytes) -> None: ...
    async def resize(self, cols: int, rows: int) -> None: ...
    async def read(self) -> AsyncIterator[bytes]: ...
    async def close(self) -> None: ...


@runtime_checkable
class BackendProtocol(Protocol):
    kind: ClassVar[str]

    async def detect(self) -> DetectResult: ...
    async def login(self, flow: LoginFlow) -> bytes: ...
    async def validate(self, credential: bytes) -> bool: ...
    async def list_models(self, credential: bytes) -> list[Model]: ...
    async def chat(
        self, request: ChatRequest, credential: bytes
    ) -> AsyncIterator[ChatStreamEvent]: ...
    async def pty(self, request: PtyRequest, credential: bytes) -> PtyHandle: ...
```

Note: `login` returns and `chat`/`pty`/`validate`/`list_models` accept `bytes` (the plaintext credential blob) — the service layer handles encryption via `VaultProtocol`. Backends never see the vault.

- [ ] **Step 8: Write `protocols/transport.py`**

```python
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from ai_accounts_core.protocol.wire import WireEvent


@runtime_checkable
class TransportProtocol(Protocol):
    async def send(self, event: WireEvent) -> None: ...
    def receive(self) -> AsyncIterator[WireEvent]: ...
    async def close(self) -> None: ...
```

Note: this references `ai_accounts_core.protocol.wire` which we build in Task 10. Tests for this module will fail until Task 10.

- [ ] **Step 9: Run tests — except transport import error expected**

```bash
uv run pytest packages/core/tests/test_protocols.py -v
```

Expected: 4 tests pass, `test_transport_protocol_exports` fails with ModuleNotFoundError on `ai_accounts_core.protocol.wire`. This is fine — Task 10 fixes it.

- [ ] **Step 10: Commit**

```bash
git add packages/core/src/ai_accounts_core/protocols packages/core/tests/test_protocols.py
git commit -m "feat(core): add Storage, Vault, Auth, Backend, Transport Protocols"
```

---

## Task 10: Wire protocol + msgspec→TS codegen

**Files:**
- Create: `packages/core/src/ai_accounts_core/protocol/__init__.py`
- Create: `packages/core/src/ai_accounts_core/protocol/wire.py`
- Create: `packages/core/tests/test_wire.py`
- Create: `scripts/codegen_wire_types.py`
- Create: `packages/ts-core/src/protocol/wire.ts` (generated)

- [ ] **Step 1: Write failing test** covering roundtrip for `ChatTokenEvent`, `ChatDoneEvent`, `PtyOutputEvent`, `ErrorEvent`, `SessionStartEvent`. Each test encodes via `encode_wire_event`, decodes via `decode_wire_event`, and asserts equality. Plus a tagged-union discrimination test that json-decodes the raw bytes and checks `parsed["type"] == "session_start"`.

- [ ] **Step 2: Run `uv run pytest packages/core/tests/test_wire.py -v`** — expect ModuleNotFoundError.

- [ ] **Step 3: Write `protocol/__init__.py`** with a one-line docstring.

- [ ] **Step 4: Write `protocol/wire.py`** — msgspec tagged union. Define `_Base(msgspec.Struct, frozen=True, kw_only=True, tag_field="type")` with `protocol_version: int = 1`. Then define 9 subclasses, each with `tag="<name>"`: `SessionStartEvent` (session_id, kind: Literal["chat", "pty"], backend_id), `SessionEndEvent` (session_id, reason: str | None), `ChatTokenEvent` (session_id, token, model: str | None), `ChatToolCallEvent` (session_id, name, arguments), `ChatDoneEvent` (session_id, tokens_in, tokens_out), `PtyOutputEvent` (session_id, data: bytes), `PtyResizeEvent` (session_id, cols, rows), `PtyExitEvent` (session_id, exit_code), `ErrorEvent` (code, message, session_id: str | None). Define `WireEvent = Annotated[Union[...], msgspec.Meta(...)]`. Export `encode_wire_event(event) -> bytes` using `msgspec.json.Encoder()` and `decode_wire_event(raw) -> WireEvent` using `msgspec.json.Decoder(WireEvent)`. Set `WIRE_PROTOCOL_VERSION = 1` at module level.

- [ ] **Step 5: Run tests** — expect pass. All protocol tests from Task 9 also pass now.

- [ ] **Step 6: Write `scripts/codegen_wire_types.py`** — imports the 9 event classes from `ai_accounts_core.protocol.wire`, iterates `__struct_fields__` and `typing.get_type_hints`, renders TS interfaces with a `type: "<tag>"` discriminator field and one line per field using a `py_to_ts` mapper (str→string, int/float→number, bool→boolean, bytes→Uint8Array, None→null, Literal→union of quoted strings, Union→union of recursive calls). Writes output to `packages/ts-core/src/protocol/wire.ts` with a `@generated` header and a `WireEvent` union type at the bottom.

- [ ] **Step 7: Run codegen**

```
uv run python scripts/codegen_wire_types.py
cat packages/ts-core/src/protocol/wire.ts
```

Expected: file contains `WIRE_PROTOCOL_VERSION = 1`, 9 `export interface` blocks, `WireEvent` union.

- [ ] **Step 8: Verify ts-core typechecks** — `pnpm --filter @ai-accounts/ts-core typecheck`.

- [ ] **Step 9: Commit** — `git commit -m "feat(core): add wire protocol + TypeScript codegen pipeline"`.

---

## Task 11: Litestar `/health` stub

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/app.py`
- Create: `packages/litestar/src/ai_accounts_litestar/config.py`
- Create: `packages/litestar/tests/__init__.py`
- Create: `packages/litestar/tests/test_health.py`

- [ ] **Step 1: Write failing test** that builds the app via `create_app(AiAccountsConfig(env="development"))`, wraps it in `litestar.testing.TestClient`, calls `GET /health`, and asserts status 200 with body `{"status": "ok", "version": "0.0.0"}`.

- [ ] **Step 2: Run** `uv run pytest packages/litestar/tests/test_health.py -v` — expect import error.

- [ ] **Step 3: Write `config.py`**

```python
from typing import Literal
import msgspec

class AiAccountsConfig(msgspec.Struct, frozen=True, kw_only=True):
    env: Literal["development", "production"] = "development"
    cors_origins: tuple[str, ...] = ()
```

- [ ] **Step 4: Write `app.py`**

```python
from litestar import Litestar, get
from ai_accounts_core import __version__ as core_version
from .config import AiAccountsConfig

@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    return {"status": "ok", "version": core_version}

def create_app(config: AiAccountsConfig) -> Litestar:
    return Litestar(route_handlers=[health], debug=config.env == "development")
```

- [ ] **Step 5: Run tests** — expect pass.

- [ ] **Step 6: Commit** — `git commit -m "feat(litestar): add create_app factory and /health route stub"`.

---

## Task 12: ts-core stub with placeholder index

**Files:**
- Modify: `packages/ts-core/src/index.ts`
- Create: `packages/ts-core/tests/index.test.ts`
- Create: `packages/ts-core/vitest.config.ts`

- [ ] **Step 1: Write `vitest.config.ts`** with `environment: 'node'`.

- [ ] **Step 2: Write failing test** that imports `version` and `WIRE_PROTOCOL_VERSION` from `../src/index` and asserts they equal `"0.0.0"` (string) and `1` (number) respectively.

- [ ] **Step 3: Update `packages/ts-core/src/index.ts`**

```
export { WIRE_PROTOCOL_VERSION } from './protocol/wire';
export type * from './protocol/wire';
export const version = '0.0.0';
```

- [ ] **Step 4: Run tests** — `pnpm --filter @ai-accounts/ts-core test`. Expect 2 passing.

- [ ] **Step 5: Commit** — `git commit -m "feat(ts-core): re-export wire protocol types and version"`.

---

**Phase 0 complete.** Verify end-to-end:

```
cd ~/Developer/Projects/ai-accounts
just test
just codegen
git diff --exit-code
just build
```

Push:

```
gh repo create ca1773130n/ai-accounts --public --source=. --remote=origin --push
```

---

# Part B — Phase 1: Accounts & Vault

## Task 13: Storage conformance suite scaffold

**Files:**
- Create: `packages/core/src/ai_accounts_core/testing/__init__.py`
- Create: `packages/core/src/ai_accounts_core/testing/storage_conformance.py`
- Create: `packages/core/src/ai_accounts_core/testing/fakes.py`
- Create: `packages/core/tests/test_fake_storage_conformance.py`

- [ ] **Step 1: Write `testing/__init__.py`**

```python
"""Reusable test utilities for Protocol conformance.

Adapter authors (in-tree and third-party) import from here to verify
their implementations match the contract.
"""

from .fakes import FakeAuth, FakeBackend, FakeStorage, FakeVault
from .storage_conformance import run_storage_conformance

__all__ = ["FakeAuth", "FakeBackend", "FakeStorage", "FakeVault", "run_storage_conformance"]
```

- [ ] **Step 2: Write `testing/fakes.py`** with five classes:

  - `_FakeBackendRepo` — in-memory dict for backends + dict for credentials. Implements all `BackendRepository` methods. `create` raises `ValueError` on duplicate id. `update` raises `KeyError` on missing id. `delete` clears both maps.
  - `_FakeSessionRepo`, `_FakeHistoryRepo`, `_FakeOnboardingRepo` — same pattern, in-memory dicts.
  - `FakeStorage` — implements `StorageProtocol`, holds one of each repo, `migrate()` and `close()` are no-ops.
  - `FakeVault` — encrypts by prefixing `b"ENC|"` + canonicalized context + `b"||"` + plaintext + SHA-256 digest of the whole thing. `decrypt` verifies the digest (tamper detection) and context match. Raises `VaultError` on mismatch. Import `VaultError` from `ai_accounts_core.protocols.vault`.
  - `FakeAuth` — returns a fixed `Principal(id="fake:anon", display_name="Anon")` for all requests.
  - `FakeBackend` — `kind = "fake"`, `detect()` returns `DetectResult(installed=True, version="fake/0.0", path="/usr/local/bin/fake")`, `login()` returns `b"fake-credential"`, `validate()` returns True iff credential equals `b"fake-credential"`, `list_models()` returns `[Model(id="fake-1", display_name="Fake Model 1")]`. `chat` and `pty` raise `NotImplementedError`. Records all calls in `self.calls` for test assertions.

- [ ] **Step 3: Write `testing/storage_conformance.py`**

```python
"""Shared conformance suite for StorageProtocol implementations.

Usage:
    import pytest
    from ai_accounts_core.testing import run_storage_conformance

    @pytest.mark.asyncio
    async def test_my_storage(tmp_path):
        storage = MyStorage(path=tmp_path / "x.db")
        await run_storage_conformance(storage)
"""

from datetime import UTC, datetime

from ai_accounts_core.domain.backend import (
    Backend, BackendCredential, BackendKind, BackendStatus,
)
from ai_accounts_core.domain.chat import ChatMessage, ChatRole, ChatSession
from ai_accounts_core.domain.onboarding import OnboardingState, OnboardingStep
from ai_accounts_core.domain.session import LiveSession, SessionKind, SessionState
from ai_accounts_core.protocols.storage import StorageProtocol


async def run_storage_conformance(storage: StorageProtocol) -> None:
    await storage.migrate()
    await _test_backend_crud(storage)
    await _test_credential_crud(storage)
    await _test_history(storage)
    await _test_sessions(storage)
    await _test_onboarding(storage)


async def _test_backend_crud(storage: StorageProtocol) -> None:
    repo = await storage.backends()
    now = datetime.now(UTC)
    backend = Backend(
        id="bkd-1", kind=BackendKind.CLAUDE, display_name="Test Claude",
        config={}, status=BackendStatus.UNCONFIGURED, created_at=now,
    )
    await repo.create(backend)
    assert await repo.get("bkd-1") == backend
    assert await repo.list() == [backend]

    updated = Backend(
        id="bkd-1", kind=BackendKind.CLAUDE, display_name="Renamed",
        config={"foo": "bar"}, status=BackendStatus.READY,
        created_at=now, updated_at=datetime.now(UTC),
    )
    await repo.update(updated)
    assert (await repo.get("bkd-1")).display_name == "Renamed"

    await repo.delete("bkd-1")
    assert await repo.get("bkd-1") is None
    assert await repo.list() == []


async def _test_credential_crud(storage: StorageProtocol) -> None:
    repo = await storage.backends()
    await repo.create(Backend(
        id="bkd-2", kind=BackendKind.OPENCODE, display_name="x", config={},
        status=BackendStatus.READY, created_at=datetime.now(UTC),
    ))
    cred = BackendCredential(
        id="crd-1", backend_id="bkd-2", ciphertext=b"\xde\xad\xbe\xef",
        key_id="local/v1", created_at=datetime.now(UTC),
    )
    await repo.put_credential(cred)
    assert await repo.get_credential("bkd-2") == cred
    await repo.delete_credential("bkd-2")
    assert await repo.get_credential("bkd-2") is None
    await repo.delete("bkd-2")


async def _test_history(storage: StorageProtocol) -> None:
    repo_b = await storage.backends()
    await repo_b.create(Backend(
        id="bkd-3", kind=BackendKind.CLAUDE, display_name="x", config={},
        status=BackendStatus.READY, created_at=datetime.now(UTC),
    ))
    history = await storage.history()
    session = ChatSession(
        id="sess-1", backend_id="bkd-3", title="First",
        created_at=datetime.now(UTC),
    )
    await history.create_session(session)
    msg = ChatMessage(
        id="msg-1", session_id="sess-1", role=ChatRole.USER,
        content="hello", created_at=datetime.now(UTC),
    )
    await history.append_message(msg)
    assert await history.list_messages("sess-1") == [msg]
    assert await history.list_sessions("bkd-3") == [session]


async def _test_sessions(storage: StorageProtocol) -> None:
    repo = await storage.sessions()
    now = datetime.now(UTC)
    session = LiveSession(
        id="live-1", kind=SessionKind.CHAT, backend_id="bkd-3",
        state=SessionState.ACTIVE, started_at=now, last_seen_at=now,
    )
    await repo.upsert(session)
    assert await repo.get("live-1") == session
    assert len(await repo.list_active()) == 1
    await repo.end("live-1")
    assert await repo.get("live-1") is None


async def _test_onboarding(storage: StorageProtocol) -> None:
    repo = await storage.onboarding()
    state = OnboardingState(id="onb-1", current_step=OnboardingStep.WELCOME)
    await repo.put(state)
    assert await repo.get("onb-1") == state
```

- [ ] **Step 4: Write `packages/core/tests/test_fake_storage_conformance.py`**

```python
import pytest
from ai_accounts_core.testing import FakeStorage, run_storage_conformance

@pytest.mark.asyncio
async def test_fake_storage_passes_conformance():
    await run_storage_conformance(FakeStorage())
```

- [ ] **Step 5: Run** `uv run pytest packages/core/tests/test_fake_storage_conformance.py -v` — expect pass.

- [ ] **Step 6: Commit** `feat(core): add Fake adapters and storage conformance suite`

---

## Task 14: SqliteStorage — schema and migration

**Files:**
- Create: `packages/core/src/ai_accounts_core/adapters/__init__.py`
- Create: `packages/core/src/ai_accounts_core/adapters/storage_sqlite/__init__.py`
- Create: `packages/core/src/ai_accounts_core/adapters/storage_sqlite/schema.sql`
- Create: `packages/core/src/ai_accounts_core/adapters/storage_sqlite/storage.py`
- Create: `packages/core/tests/test_sqlite_storage.py`

- [ ] **Step 1: Write failing conformance test**

```python
from pathlib import Path
import pytest
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.testing import run_storage_conformance


@pytest.mark.asyncio
async def test_sqlite_storage_conformance(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await run_storage_conformance(storage)
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_migrate_is_idempotent(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "test.db"))
    await storage.migrate()
    await storage.migrate()
    await storage.close()
```

- [ ] **Step 2: Write `schema.sql`** with these tables (all use `IF NOT EXISTS`):

  - `schema_version(version INTEGER PRIMARY KEY)`
  - `backends(id PK, kind, display_name, config, status, created_at, updated_at, last_error)`
  - `backend_credentials(id PK, backend_id UNIQUE REFERENCES backends ON DELETE CASCADE, ciphertext BLOB, key_id, created_at, expires_at)`
  - `chat_sessions(id PK, backend_id REFERENCES backends ON DELETE CASCADE, title, created_at, updated_at, model)`
  - `chat_messages(id PK, session_id REFERENCES chat_sessions ON DELETE CASCADE, role, content, created_at, model, tokens_in, tokens_out)`
  - Index `idx_chat_messages_session ON chat_messages(session_id)`
  - `live_sessions(id PK, kind, backend_id, state, started_at, last_seen_at)`
  - `onboarding(id PK, current_step, selected_backend_kind, created_backend_id, error)`

- [ ] **Step 3: Write `storage_sqlite/storage.py`** — four repository classes (`_SqliteBackendRepo`, `_SqliteSessionRepo`, `_SqliteHistoryRepo`, `_SqliteOnboardingRepo`) all taking an `aiosqlite.Connection` in `__init__`, plus the public `SqliteStorage` class. Helpers: `_iso(dt) -> dt.isoformat()`, `_parse_dt(s) -> datetime.fromisoformat(s) if s else None`. Constants: `_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()`, `_CURRENT_VERSION = 1`.

  `SqliteStorage` holds `self._conn: aiosqlite.Connection | None = None` and `self._path: str`. `_ensure_conn()` opens the connection on first call and enables `PRAGMA foreign_keys = ON`. `migrate()` runs `conn.executescript(_SCHEMA)`, then checks `MAX(version)` in `schema_version` and inserts `_CURRENT_VERSION` if missing. Each of the four `backends()`, `sessions()`, `history()`, `onboarding()` methods returns a fresh repo wrapping the shared connection.

  Each repo translates between dataclass fields and SQL rows, using parameterized queries (never string interpolation). `_row_to_backend(row)` builds a `Backend` with `config=json.loads(row[3])`, `status=BackendStatus(row[4])`, etc. Credentials: `get_credential` uses `SELECT ... WHERE backend_id = ?` (not by credential id). `put_credential` uses `INSERT OR REPLACE`. Commit after every write.

- [ ] **Step 4: Write `adapters/storage_sqlite/__init__.py`**

```python
from .storage import SqliteStorage
__all__ = ["SqliteStorage"]
```

- [ ] **Step 5: Package the schema file** — add to `packages/core/pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/ai_accounts_core/adapters/storage_sqlite/schema.sql" = "ai_accounts_core/adapters/storage_sqlite/schema.sql"
```

- [ ] **Step 6: Run tests** — `uv run pytest packages/core/tests/test_sqlite_storage.py -v`. Expect both pass.

- [ ] **Step 7: Commit** `feat(core): add SqliteStorage adapter with conformance tests`

---

## Task 15: Vault conformance suite + EnvKeyVault (security-critical)

**Files:**
- Create: `packages/core/src/ai_accounts_core/testing/vault_conformance.py`
- Modify: `packages/core/src/ai_accounts_core/testing/__init__.py`
- Create: `packages/core/src/ai_accounts_core/adapters/vault_envkey/__init__.py`
- Create: `packages/core/src/ai_accounts_core/adapters/vault_envkey/vault.py`
- Create: `packages/core/tests/test_env_key_vault.py`
- Create: `packages/core/tests/test_fake_vault_conformance.py`

- [ ] **Step 1: Write `testing/vault_conformance.py`**

```python
"""Shared conformance suite for VaultProtocol implementations."""
import pytest
from ai_accounts_core.protocols.vault import VaultError, VaultProtocol


async def run_vault_conformance(vault: VaultProtocol) -> None:
    await _roundtrip(vault)
    await _context_binding(vault)
    await _tamper_detection(vault)
    await _key_id_exposed(vault)


async def _roundtrip(vault: VaultProtocol) -> None:
    plaintext = b"super-secret-api-key-abc123"
    ct = await vault.encrypt(plaintext, context={"backend_id": "bkd-1"})
    pt = await vault.decrypt(ct, context={"backend_id": "bkd-1"})
    assert pt == plaintext


async def _context_binding(vault: VaultProtocol) -> None:
    ct = await vault.encrypt(b"x", context={"backend_id": "bkd-A"})
    with pytest.raises(VaultError):
        await vault.decrypt(ct, context={"backend_id": "bkd-B"})


async def _tamper_detection(vault: VaultProtocol) -> None:
    ct = bytearray(await vault.encrypt(b"payload", context={"backend_id": "bkd-1"}))
    ct[-1] ^= 0xFF
    with pytest.raises(VaultError):
        await vault.decrypt(bytes(ct), context={"backend_id": "bkd-1"})


async def _key_id_exposed(vault: VaultProtocol) -> None:
    key_id = await vault.current_key_id()
    assert isinstance(key_id, str) and key_id
```

- [ ] **Step 2: Export from `testing/__init__.py`** — add `run_vault_conformance` to imports and `__all__`.

- [ ] **Step 3: Write `adapters/vault_envkey/vault.py`**

```python
from __future__ import annotations

import base64
import hashlib
import logging
import os
import struct
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ai_accounts_core.protocols.vault import VaultError

log = logging.getLogger(__name__)

_VERSION = 1
_NONCE_LEN = 12
_KEY_ID = "envkey://v1"


def _canonical_context(context: dict[str, str]) -> bytes:
    items = sorted(context.items())
    return b"|".join(f"{k}={v}".encode() for k, v in items)


class EnvKeyVault:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("EnvKeyVault requires a 32-byte (AES-256) key")
        self._aesgcm = AESGCM(key)

    @classmethod
    def from_env(
        cls,
        *,
        env: Literal["development", "production"] = "development",
        env_var: str = "AI_ACCOUNTS_VAULT_KEY",
    ) -> "EnvKeyVault":
        raw = os.environ.get(env_var)
        if raw:
            try:
                key = base64.b64decode(raw)
            except Exception as exc:
                raise RuntimeError(f"{env_var} is not valid base64") from exc
            if len(key) != 32:
                raise RuntimeError(f"{env_var} must decode to 32 bytes (got {len(key)})")
            return cls(key)

        if env == "production":
            raise RuntimeError(
                f"ai-accounts refuses to start in production without a vault key. "
                f"Set {env_var} to a base64-encoded 32-byte key."
            )

        log.warning(
            "ai-accounts: no %s set, deriving a dev-only fallback vault key. "
            "DO NOT use this in production.",
            env_var,
        )
        fallback_seed = b"ai-accounts-dev-insecure-fallback-seed-v1"
        derived = hashlib.sha256(fallback_seed).digest()
        return cls(derived)

    async def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        aad = _canonical_context(context)
        ct = self._aesgcm.encrypt(nonce, plaintext, aad)
        return struct.pack("!B", _VERSION) + nonce + ct

    async def decrypt(self, ciphertext: bytes, *, context: dict[str, str]) -> bytes:
        if len(ciphertext) < 1 + _NONCE_LEN + 16:
            raise VaultError("ciphertext too short")
        if ciphertext[0] != _VERSION:
            raise VaultError(f"unknown vault envelope version {ciphertext[0]}")
        nonce = ciphertext[1 : 1 + _NONCE_LEN]
        ct = ciphertext[1 + _NONCE_LEN :]
        aad = _canonical_context(context)
        try:
            return self._aesgcm.decrypt(nonce, ct, aad)
        except InvalidTag as exc:
            raise VaultError("vault decryption failed (tamper or wrong context/key)") from exc

    async def current_key_id(self) -> str:
        return _KEY_ID

    async def rotate(self, old_key_id: str) -> None:
        raise NotImplementedError("EnvKeyVault rotation not supported in v0.1")
```

- [ ] **Step 4: Write `adapters/vault_envkey/__init__.py`**

```python
from .vault import EnvKeyVault
__all__ = ["EnvKeyVault"]
```

- [ ] **Step 5: Write `tests/test_env_key_vault.py`**

```python
import base64
import logging
import pytest

from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.testing import run_vault_conformance


@pytest.mark.asyncio
async def test_env_key_vault_conformance(monkeypatch):
    key_b64 = base64.b64encode(b"\x00" * 32).decode()
    monkeypatch.setenv("AI_ACCOUNTS_VAULT_KEY", key_b64)
    vault = EnvKeyVault.from_env()
    await run_vault_conformance(vault)


def test_production_mode_refuses_derived_key(monkeypatch):
    monkeypatch.delenv("AI_ACCOUNTS_VAULT_KEY", raising=False)
    with pytest.raises(RuntimeError, match="vault key"):
        EnvKeyVault.from_env(env="production")


@pytest.mark.asyncio
async def test_dev_mode_derives_key_with_warning(monkeypatch, caplog):
    monkeypatch.delenv("AI_ACCOUNTS_VAULT_KEY", raising=False)
    caplog.set_level(logging.WARNING)
    vault = EnvKeyVault.from_env(env="development")
    assert any("dev" in rec.message.lower() for rec in caplog.records)
    ct = await vault.encrypt(b"hi", context={"k": "v"})
    assert await vault.decrypt(ct, context={"k": "v"}) == b"hi"
```

- [ ] **Step 6: Write `tests/test_fake_vault_conformance.py`**

```python
import pytest
from ai_accounts_core.testing import FakeVault, run_vault_conformance

@pytest.mark.asyncio
async def test_fake_vault_passes_conformance():
    await run_vault_conformance(FakeVault())
```

- [ ] **Step 7: Run tests**

```
uv run pytest packages/core/tests/test_env_key_vault.py packages/core/tests/test_fake_vault_conformance.py -v
```

Expected: all pass. (Task 13's FakeVault already includes the SHA-256 integrity tag needed to pass tamper detection.)

- [ ] **Step 8: Commit** `feat(core): add EnvKeyVault (AES-256-GCM) and vault conformance suite`

---

## Task 16: Auth adapters — NoAuth + ApiKeyAuth

**Files:**
- Create: `packages/core/src/ai_accounts_core/adapters/auth_noauth.py`
- Create: `packages/core/src/ai_accounts_core/adapters/auth_apikey.py`
- Create: `packages/core/tests/test_auth_adapters.py`

- [ ] **Step 1: Write failing tests** covering: `NoAuth` returns a `Principal(id="local")` for any request; `ApiKeyAuth.from_env` reads `AI_ACCOUNTS_API_KEY`; valid `Bearer <token>` header returns the principal; missing header returns `None`; wrong token returns `None`; the implementation uses `hmac.compare_digest` (not `==`) — enforce via a grep of the source file in-test.

- [ ] **Step 2: Write `auth_noauth.py`**

```python
import logging
from ai_accounts_core.domain.principal import Principal
from ai_accounts_core.protocols.auth import RequestContext

log = logging.getLogger(__name__)


class NoAuth:
    _LOCAL_PRINCIPAL = Principal(
        id="local", display_name="Local Dev", scopes=frozenset({"*"})
    )

    def __init__(self) -> None:
        log.warning("ai-accounts: using NoAuth — ALL requests authenticated as 'local'.")

    async def authenticate(self, request: RequestContext) -> Principal | None:
        return self._LOCAL_PRINCIPAL
```

- [ ] **Step 3: Write `auth_apikey.py`**

```python
import hmac
import os
from ai_accounts_core.domain.principal import Principal
from ai_accounts_core.protocols.auth import RequestContext

_PREFIX = "bearer "


class ApiKeyAuth:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("ApiKeyAuth requires a non-empty token")
        self._token = token
        self._principal = Principal(
            id="api_key", display_name="API Key", scopes=frozenset({"*"})
        )

    @classmethod
    def from_env(cls, env_var: str = "AI_ACCOUNTS_API_KEY") -> "ApiKeyAuth":
        token = os.environ.get(env_var, "")
        if not token:
            raise RuntimeError(f"{env_var} is not set; ApiKeyAuth cannot start.")
        return cls(token)

    async def authenticate(self, request: RequestContext) -> Principal | None:
        header = request.headers.get("authorization") or request.headers.get("Authorization")
        if not header or not header.lower().startswith(_PREFIX):
            return None
        presented = header[len(_PREFIX):]
        if not hmac.compare_digest(presented, self._token):
            return None
        return self._principal
```

- [ ] **Step 4: Run + commit** `feat(core): add NoAuth and ApiKeyAuth adapters`

---

## Task 17: ID generator utility

**Files:**
- Create: `packages/core/src/ai_accounts_core/ids.py`
- Create: `packages/core/tests/test_ids.py`

- [ ] **Step 1: Test** that `new_id("bkd")` returns a string starting with `"bkd-"`, has length `len("bkd-") + 12`, and two calls produce different values.

- [ ] **Step 2: Implementation**

```python
import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits


def new_id(prefix: str, length: int = 12) -> str:
    return f"{prefix}-" + "".join(secrets.choice(_ALPHABET) for _ in range(length))
```

- [ ] **Step 3: Run + commit** `feat(core): add prefixed ID generator`

---

## Task 18: AccountService

**Files:**
- Create: `packages/core/src/ai_accounts_core/services/__init__.py`
- Create: `packages/core/src/ai_accounts_core/services/errors.py`
- Create: `packages/core/src/ai_accounts_core/services/accounts.py`
- Create: `packages/core/tests/test_account_service.py`

**Important refactor needed first:** Change `Backend.kind` from the `BackendKind` enum to a plain `str`, with `BackendKind` kept as a namespace of string constants. This lets third-party backends (and `FakeBackend` in tests) register their own `kind` values without editing the core enum.

Update `domain/backend.py`:

```python
class BackendKind:
    CLAUDE = "claude"
    OPENCODE = "opencode"
    GEMINI = "gemini"
    CODEX = "codex"


class Backend(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    kind: str   # was BackendKind
    display_name: str
    config: dict
    status: BackendStatus
    created_at: datetime
    updated_at: datetime | None = None
    last_error: str | None = None
```

Update `test_domain.py` assertions from `is BackendKind.CLAUDE` to `== BackendKind.CLAUDE`. Update `_SqliteBackendRepo._row_to_backend` to pass `kind=row[1]` (no enum wrap). Update the storage conformance suite to use `kind=BackendKind.CLAUDE` (still works — the constants are strings). Re-run all existing tests to confirm they still pass before proceeding.

- [ ] **Step 1: Write failing test covering**: create with known kind persists and returns; create with unknown kind raises `BackendKindUnknown`; list returns all; get missing raises `BackendNotFound`; delete cascades to credential; `login` + `validate` happy path transitions to `READY` status.

  Use `FakeStorage`, `FakeVault`, and `FakeBackend` via:
  ```python
  service = AccountService(
      storage=FakeStorage(),
      vault=FakeVault(),
      backends={"fake": FakeBackend()},
  )
  ```

- [ ] **Step 2: Write `services/errors.py`**

```python
class ServiceError(Exception):
    code: str = "service_error"

class BackendNotFound(ServiceError):
    code = "backend_not_found"

class BackendAlreadyExists(ServiceError):
    code = "backend_already_exists"

class BackendKindUnknown(ServiceError):
    code = "backend_kind_unknown"

class BackendNotReady(ServiceError):
    code = "backend_not_ready"

class BackendValidationFailed(ServiceError):
    code = "backend_validation_failed"

class CredentialMissing(ServiceError):
    code = "credential_missing"
```

- [ ] **Step 3: Write `services/accounts.py`** — `AccountService` class with:

  - `__init__(self, *, storage, vault, backends: Mapping[str, BackendProtocol])` stores refs, copies `backends` into `self._backend_impls: dict`.
  - `async create(kind, *, display_name, config=None) -> Backend`: raises `BackendKindUnknown` if kind not in `_backend_impls`; builds `Backend(id=new_id("bkd"), kind=kind, display_name=..., config=config or {}, status=BackendStatus.UNCONFIGURED, created_at=_now())`; calls `(await storage.backends()).create(backend)`; returns it.
  - `async get(backend_id) -> Backend`: fetch; raise `BackendNotFound` if `None`.
  - `async list() -> list[Backend]`: delegate to repo.
  - `async delete(backend_id)`: verify exists via `get`, then `repo.delete(backend_id)` (SQLite cascade drops credential).
  - `async detect(backend_id) -> DetectResult`: fetches backend, calls `impl.detect()`, if `not result.installed` updates status to `NEEDS_LOGIN` with last_error, returns result.
  - `async login(backend_id, *, flow_kind, inputs) -> Backend`: fetches backend, calls `impl.login(LoginFlow(kind=flow_kind, inputs=inputs))` to get plaintext bytes, encrypts via `vault.encrypt(plaintext, context={"backend_id": backend_id})`, stores `BackendCredential` with `key_id=await vault.current_key_id()`, transitions status to `VALIDATING`, returns updated backend.
  - `async validate(backend_id) -> Backend`: loads stored credential (raise `CredentialMissing` if none), decrypts with matching context, calls `impl.validate(plaintext)`. On False: set status `ERROR` with last_error and raise `BackendValidationFailed`. On True: set status `READY`, return.
  - `async list_models(backend_id) -> list[Model]`: raise `BackendNotReady` if status != READY, decrypt credential, call `impl.list_models(plaintext)`.
  - Private `_update_status(backend, status, *, last_error=...)`: rebuild a `Backend` struct (they're frozen) with new status/updated_at/last_error, call repo.update, return the new instance.

- [ ] **Step 4: Write `services/__init__.py`**

```python
from .accounts import AccountService
from .errors import (
    BackendAlreadyExists, BackendKindUnknown, BackendNotFound,
    BackendNotReady, BackendValidationFailed, CredentialMissing, ServiceError,
)

__all__ = [
    "AccountService", "BackendAlreadyExists", "BackendKindUnknown",
    "BackendNotFound", "BackendNotReady", "BackendValidationFailed",
    "CredentialMissing", "ServiceError",
]
```

- [ ] **Step 5: Run all core tests** — `uv run pytest packages/core -v`. All must pass.

- [ ] **Step 6: Commit** `feat(core): add AccountService with create/list/get/delete/login/validate`

---

## Task 19: ClaudeBackend

**Files:**
- Create: `packages/core/src/ai_accounts_core/backends/__init__.py`
- Create: `packages/core/src/ai_accounts_core/backends/claude.py`
- Create: `packages/core/tests/test_claude_backend.py`

- [ ] **Step 1: Write failing tests** covering: `detect` uses `shutil.which` + `--version` subprocess and returns `DetectResult(installed=True, version=..., path=...)`; `detect` returns `installed=False` when `which` is None; `login` with `flow.kind == "api_key"` returns `inputs["api_key"].encode()`; unknown flow raises `ValueError`; `validate` runs the CLI with `ANTHROPIC_API_KEY` env var and returns True on rc=0 / False otherwise; `list_models` parses JSON array into `Model` instances.

  Mock subprocess via `patch.object(backend, "_run", new=AsyncMock(return_value=(rc, stdout, stderr)))`.

- [ ] **Step 2: Write `backends/claude.py`** — `ClaudeBackend(BackendProtocol)` with:

  - `kind = "claude"`, `_CLI_NAME = "claude"`
  - `async detect()`: `path = shutil.which(self._CLI_NAME)`; if None → `DetectResult(installed=False)`; else run `[path, "--version"]` via `_run` and return installed=True with version parsed from stdout.
  - `async login(flow)`: if `flow.kind == "api_key"` return `flow.inputs["api_key"].strip().encode()` (raise ValueError if empty); else raise ValueError for unsupported flow.
  - `async validate(credential)`: run `[path, "auth", "status"]` with `env={"ANTHROPIC_API_KEY": credential.decode(), **os.environ}`; return rc == 0.
  - `async list_models(credential)`: run `[path, "models", "list", "--json"]` with the env var set; parse `json.loads(stdout)` and return `[Model(id=..., display_name=..., context_window=...) for item in raw]`. Return `[]` on rc != 0.
  - `async chat(...)` and `async pty(...)` raise `NotImplementedError` with a "lands in Phase 3/4" message.
  - Private `async _run(spec: dict) -> tuple[int, bytes, bytes]`: uses `asyncio.create_subprocess_exec` with the argv and env from `spec`, pipes stdout/stderr, awaits `communicate()`, returns `(proc.returncode or 0, stdout, stderr)`.

- [ ] **Step 3: Write `backends/__init__.py`**

```python
from .claude import ClaudeBackend
__all__ = ["ClaudeBackend"]
```

- [ ] **Step 4: Run + commit** `feat(core): add ClaudeBackend (detect, login, validate, list_models)`

---

## Task 20: OpenCodeBackend

**Files:**
- Create: `packages/core/src/ai_accounts_core/backends/opencode.py`
- Modify: `packages/core/src/ai_accounts_core/backends/__init__.py`
- Create: `packages/core/tests/test_opencode_backend.py`

- [ ] **Step 1: Write tests** mirroring the Claude tests but with `kind = "opencode"`, CLI name `opencode`, env var `OPENCODE_API_KEY`, and validate argv `["opencode", "auth", "check"]`.

- [ ] **Step 2: Write `backends/opencode.py`** — structurally identical to `claude.py`, changing:
  - `kind = "opencode"`
  - `_CLI_NAME = "opencode"`
  - `validate` uses env key `OPENCODE_API_KEY` and argv `[path, "auth", "check"]`
  - `list_models` uses argv `[path, "models", "--json"]`

- [ ] **Step 3: Update `backends/__init__.py`**

```python
from .claude import ClaudeBackend
from .opencode import OpenCodeBackend
__all__ = ["ClaudeBackend", "OpenCodeBackend"]
```

- [ ] **Step 4: Run + commit** `feat(core): add OpenCodeBackend`

---

## Task 21: Litestar config, DI wiring, and production guard

**Files:**
- Modify: `packages/litestar/src/ai_accounts_litestar/config.py`
- Create: `packages/litestar/src/ai_accounts_litestar/di.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Create: `packages/litestar/tests/test_config_guard.py`

> **Ordering note:** Task 21's `app.py` imports `BackendsController` and `service_error_handler`, which are defined in Task 22. Do Tasks 21 and 22 back-to-back. In Task 21, create stub files first (`routes/__init__.py` empty; `routes/backends.py` with `from litestar import Controller; class BackendsController(Controller): path = "/api/v1/backends"`; `errors.py` with `def service_error_handler(request, exc): from litestar import Response; return Response({}, status_code=500)`). Task 22 fills them in. The config-guard tests only exercise `_enforce_production_guards`, so stubs suffice for Task 21 to pass.

- [ ] **Step 1: Write failing tests for production guard** covering:
  - `env="production"` with `NoAuth` → raises `RuntimeError` matching `"NoAuth"`
  - `env="production"` with `cors_origins=("*",)` → raises matching `"wildcard"`
  - `env="production"` with `FakeVault` → raises matching `"fake"`
  - `env="development"` with anything → returns an app (no raise)

- [ ] **Step 2: Update `config.py`**

```python
from typing import Any, Literal
import msgspec

class AiAccountsConfig(msgspec.Struct, kw_only=True):
    env: Literal["development", "production"] = "development"
    storage: Any = None
    vault: Any = None
    auth: Any = None
    backends: tuple[Any, ...] = ()
    cors_origins: tuple[str, ...] = ()
```

`Any` is used because Protocols can't be validated statically by msgspec; guard logic runs at `create_app` time instead.

- [ ] **Step 3: Update `app.py`**

```python
from litestar import Litestar, get
from litestar.config.cors import CORSConfig
from litestar.di import Provide

from ai_accounts_core import __version__ as core_version
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import ServiceError

from .config import AiAccountsConfig
from .errors import service_error_handler
from .routes.backends import BackendsController


@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    return {"status": "ok", "version": core_version}


def _enforce_production_guards(config: AiAccountsConfig) -> None:
    if config.env != "production":
        return
    violations: list[str] = []
    vault_cls = type(config.vault).__name__
    if "Fake" in vault_cls:
        violations.append(f"vault is a test fake ({vault_cls})")
    if isinstance(config.auth, NoAuth):
        violations.append("auth is NoAuth; use ApiKeyAuth or an OIDC adapter")
    if "*" in config.cors_origins:
        violations.append("cors_origins contains wildcard '*'")
    if not config.cors_origins:
        violations.append("cors_origins is empty in production")
    if violations:
        raise RuntimeError(
            "ai-accounts refuses to start in production mode:\n  - "
            + "\n  - ".join(violations)
        )


def create_app(config: AiAccountsConfig) -> Litestar:
    _enforce_production_guards(config)

    impls = {b.kind: b for b in config.backends}
    account_service = AccountService(
        storage=config.storage, vault=config.vault, backends=impls
    )

    dependencies = {
        "config": Provide(lambda: config, sync_to_thread=False),
        "account_service": Provide(lambda: account_service, sync_to_thread=False),
    }

    cors_config = (
        CORSConfig(allow_origins=list(config.cors_origins)) if config.cors_origins else None
    )

    async def _startup(app: Litestar) -> None:
        await config.storage.migrate()

    return Litestar(
        route_handlers=[health, BackendsController],
        dependencies=dependencies,
        cors_config=cors_config,
        exception_handlers={ServiceError: service_error_handler},
        on_startup=[_startup],
        debug=config.env == "development",
    )
```

- [ ] **Step 4: Run + commit** `feat(litestar): add production-mode guard, DI, and startup migration`

---

## Task 22: Litestar `/api/v1/backends` routes

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/__init__.py`
- Create: `packages/litestar/src/ai_accounts_litestar/routes/backends.py`
- Create: `packages/litestar/src/ai_accounts_litestar/dto.py`
- Create: `packages/litestar/src/ai_accounts_litestar/errors.py`
- Create: `packages/litestar/tests/test_backends_routes.py`

- [ ] **Step 1: Write failing route tests** using `litestar.testing.TestClient`, a real `SqliteStorage(tmp_path/"test.db")`, `FakeVault()`, `NoAuth()`, and `(FakeBackend(),)` as the backends tuple. Cover:
  - `GET /api/v1/backends` empty → `{"items": []}`
  - `POST /api/v1/backends` with kind="fake" → 201 with id, kind, status="unconfigured"
  - `GET /api/v1/backends/bkd-nope` → 404 with body `{"error": {"code": "backend_not_found", ...}}`
  - `POST` with kind="martian" → 400, code `backend_kind_unknown`
  - `POST /api/v1/backends/{id}/detect` → 200, `installed: true`
  - Full login→validate happy path → status becomes `"ready"`
  - `DELETE` → 204; subsequent `GET` → 404

- [ ] **Step 2: Write `dto.py`**

```python
import msgspec
from ai_accounts_core.domain.backend import Backend, DetectResult


class BackendDTO(msgspec.Struct, kw_only=True):
    id: str
    kind: str
    display_name: str
    status: str
    config: dict
    last_error: str | None = None

    @classmethod
    def from_domain(cls, backend: Backend) -> "BackendDTO":
        return cls(
            id=backend.id,
            kind=backend.kind,
            display_name=backend.display_name,
            status=backend.status.value,
            config=backend.config,
            last_error=backend.last_error,
        )


class BackendListDTO(msgspec.Struct, kw_only=True):
    items: list[BackendDTO]


class CreateBackendRequest(msgspec.Struct, kw_only=True):
    kind: str
    display_name: str
    config: dict = {}


class LoginRequest(msgspec.Struct, kw_only=True):
    flow_kind: str
    inputs: dict[str, str] = {}


class DetectResultDTO(msgspec.Struct, kw_only=True):
    installed: bool
    version: str | None = None
    path: str | None = None
    notes: str | None = None

    @classmethod
    def from_domain(cls, r: DetectResult) -> "DetectResultDTO":
        return cls(installed=r.installed, version=r.version, path=r.path, notes=r.notes)
```

- [ ] **Step 3: Write `errors.py`**

```python
from litestar import Request, Response
from ai_accounts_core.services.errors import ServiceError

_STATUS_BY_CODE = {
    "backend_not_found": 404,
    "backend_kind_unknown": 400,
    "backend_already_exists": 409,
    "backend_not_ready": 409,
    "backend_validation_failed": 400,
    "credential_missing": 409,
}


def service_error_handler(request: Request, exc: ServiceError) -> Response:
    status = _STATUS_BY_CODE.get(exc.code, 500)
    return Response(
        content={"error": {"code": exc.code, "message": str(exc) or exc.code}},
        status_code=status,
    )
```

- [ ] **Step 4: Write `routes/backends.py`**

```python
from litestar import Controller, delete, get, post, status_codes

from ai_accounts_core.services.accounts import AccountService

from ..dto import (
    BackendDTO, BackendListDTO, CreateBackendRequest,
    DetectResultDTO, LoginRequest,
)


class BackendsController(Controller):
    path = "/api/v1/backends"
    tags = ["backends"]

    @get("/", sync_to_thread=False)
    async def list_backends(self, account_service: AccountService) -> BackendListDTO:
        items = await account_service.list()
        return BackendListDTO(items=[BackendDTO.from_domain(b) for b in items])

    @post("/", status_code=status_codes.HTTP_201_CREATED)
    async def create_backend(
        self, data: CreateBackendRequest, account_service: AccountService
    ) -> BackendDTO:
        created = await account_service.create(
            data.kind, display_name=data.display_name, config=data.config
        )
        return BackendDTO.from_domain(created)

    @get("/{backend_id:str}")
    async def get_backend(
        self, backend_id: str, account_service: AccountService
    ) -> BackendDTO:
        return BackendDTO.from_domain(await account_service.get(backend_id))

    @delete("/{backend_id:str}")
    async def delete_backend(
        self, backend_id: str, account_service: AccountService
    ) -> None:
        await account_service.delete(backend_id)

    @post("/{backend_id:str}/detect")
    async def detect(
        self, backend_id: str, account_service: AccountService
    ) -> DetectResultDTO:
        return DetectResultDTO.from_domain(await account_service.detect(backend_id))

    @post("/{backend_id:str}/login")
    async def login(
        self, backend_id: str, data: LoginRequest, account_service: AccountService
    ) -> BackendDTO:
        updated = await account_service.login(
            backend_id, flow_kind=data.flow_kind, inputs=data.inputs
        )
        return BackendDTO.from_domain(updated)

    @post("/{backend_id:str}/validate")
    async def validate(
        self, backend_id: str, account_service: AccountService
    ) -> BackendDTO:
        return BackendDTO.from_domain(await account_service.validate(backend_id))
```

- [ ] **Step 5: Run + commit** `feat(litestar): add /api/v1/backends routes and error mapping`

---

## Task 23: OpenAPI schema dump + ts-core API client

**Files:**
- Create: `scripts/codegen_openapi.py`
- Create: `packages/ts-core/src/client/index.ts`
- Create: `packages/ts-core/src/client/openapi.json` (generated)
- Create: `packages/ts-core/src/client/generated.ts` (generated)
- Create: `packages/ts-core/tests/client.test.ts`
- Modify: `packages/ts-core/package.json` (add `openapi-typescript` devDep)

- [ ] **Step 1: Add openapi-typescript**

```
cd ~/Developer/Projects/ai-accounts
pnpm add -Dw openapi-typescript
```

- [ ] **Step 2: Write `scripts/codegen_openapi.py`** — builds an app via `create_app(AiAccountsConfig(env="development", storage=SqliteStorage(":memory:"), vault=FakeVault(), auth=NoAuth(), backends=(ClaudeBackend(), OpenCodeBackend())))`, serializes `app.openapi_schema.to_schema()` to `packages/ts-core/src/client/openapi.json`, then shells out: `subprocess.run(["pnpm", "exec", "openapi-typescript", str(JSON_OUT), "-o", str(TS_OUT)], check=True, cwd=REPO)`.

- [ ] **Step 3: Write `packages/ts-core/src/client/index.ts`** — a small fetch wrapper (not auto-generated client — just typed helpers using the generated `paths` type for compile-time validation).

```typescript
import type { paths } from './generated';

export type BackendDTO = {
  id: string;
  kind: string;
  display_name: string;
  status: string;
  config: Record<string, unknown>;
  last_error: string | null;
};

export interface ClientOptions {
  baseUrl: string;
  token?: string;
  fetch?: typeof fetch;
}

export interface ApiError extends Error {
  code: string;
  status: number;
}

async function toError(r: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = r.statusText;
  try {
    const body = (await r.json()) as { error?: { code?: string; message?: string } };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
    }
  } catch {}
  const err = new Error(message) as ApiError;
  err.code = code;
  err.status = r.status;
  return err;
}

export class AiAccountsClient {
  private readonly baseUrl: string;
  private readonly token: string | undefined;
  private readonly _fetch: typeof fetch;

  constructor(opts: ClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '');
    this.token = opts.token;
    this._fetch = opts.fetch ?? fetch;
  }

  private headers(): HeadersInit {
    const h: Record<string, string> = { 'content-type': 'application/json' };
    if (this.token) h['authorization'] = `Bearer ${this.token}`;
    return h;
  }

  async listBackends(): Promise<{ items: BackendDTO[] }> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/backends`, { headers: this.headers() });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { items: BackendDTO[] };
  }

  async createBackend(input: { kind: string; display_name: string; config?: Record<string, unknown> }): Promise<BackendDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/backends`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ config: {}, ...input }),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as BackendDTO;
  }

  async getBackend(id: string): Promise<BackendDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/backends/${encodeURIComponent(id)}`, { headers: this.headers() });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as BackendDTO;
  }

  async deleteBackend(id: string): Promise<void> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/backends/${encodeURIComponent(id)}`, {
      method: 'DELETE', headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
  }

  async detectBackend(id: string) { return this.postAction(id, 'detect'); }
  async loginBackend(id: string, flowKind: string, inputs: Record<string, string>) {
    return this.postAction(id, 'login', { flow_kind: flowKind, inputs });
  }
  async validateBackend(id: string) { return this.postAction(id, 'validate'); }

  private async postAction(id: string, action: string, body?: unknown): Promise<unknown> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(id)}/${action}`,
      {
        method: 'POST',
        headers: this.headers(),
        body: body ? JSON.stringify(body) : undefined,
      }
    );
    if (!r.ok) throw await toError(r);
    return r.json();
  }
}
```

- [ ] **Step 4: Update `packages/ts-core/src/index.ts`**

```typescript
export { WIRE_PROTOCOL_VERSION } from './protocol/wire';
export type * from './protocol/wire';
export { AiAccountsClient } from './client';
export type { ClientOptions, ApiError, BackendDTO } from './client';

export const version = '0.0.0';
```

- [ ] **Step 5: Write `tests/client.test.ts`** covering:
  - `listBackends` returns items and calls `fetch` with the right URL
  - 404 responses throw an `ApiError` with `code` from the error envelope
  - `Bearer` token is added to headers when `token` is configured

Use `vi.fn().mockResolvedValue({ ok, status, statusText, json: async () => body })` as a fake Fetch.

- [ ] **Step 6: Run codegen, typecheck, tests**

```
uv run python scripts/codegen_openapi.py
pnpm --filter @ai-accounts/ts-core typecheck
pnpm --filter @ai-accounts/ts-core test
```

- [ ] **Step 7: Commit** `feat(ts-core): add OpenAPI codegen and AiAccountsClient wrapper`

---

## Task 24: ts-core `accountWizard` state machine

**Files:**
- Create: `packages/ts-core/src/machines/accountWizard.ts`
- Create: `packages/ts-core/tests/accountWizard.test.ts`
- Modify: `packages/ts-core/src/index.ts`

- [ ] **Step 1: Write failing tests** covering the happy path (idle → picking_kind → detecting → entering_credential → validating → done), the error path when `detectBackend` returns `installed: false`, the error path when `validateBackend` rejects, and `reset()` returning to `idle`. Use `vi.fn().mockResolvedValue(...)` to stub the client methods.

- [ ] **Step 2: Write `machines/accountWizard.ts`**

```typescript
import type { AiAccountsClient, BackendDTO } from '../client';

export type WizardState =
  | 'idle' | 'picking_kind' | 'detecting' | 'entering_credential'
  | 'validating' | 'done' | 'error';

export interface WizardDetection {
  installed: boolean;
  version?: string | null;
  path?: string | null;
  notes?: string | null;
}

export interface AccountWizard {
  readonly state: WizardState;
  readonly kind: string | undefined;
  readonly detection: WizardDetection | undefined;
  readonly backend: BackendDTO | undefined;
  readonly error: string | undefined;
  subscribe(listener: () => void): () => void;
  start(): void;
  pickKind(kind: string): Promise<void>;
  submitCredential(flowKind: string, inputs: Record<string, string>): Promise<void>;
  reset(): void;
}

export function createAccountWizard(opts: {
  client: AiAccountsClient;
  defaultDisplayName?: string;
}): AccountWizard {
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((l) => l());

  let state: WizardState = 'idle';
  let kind: string | undefined;
  let detection: WizardDetection | undefined;
  let backend: BackendDTO | undefined;
  let error: string | undefined;

  return {
    get state() { return state; },
    get kind() { return kind; },
    get detection() { return detection; },
    get backend() { return backend; },
    get error() { return error; },

    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },

    start() {
      state = 'picking_kind';
      kind = undefined;
      detection = undefined;
      backend = undefined;
      error = undefined;
      emit();
    },

    async pickKind(chosen) {
      kind = chosen;
      state = 'detecting';
      emit();
      try {
        backend = await opts.client.createBackend({
          kind: chosen,
          display_name: opts.defaultDisplayName ?? `${chosen} account`,
        });
        detection = (await opts.client.detectBackend(backend.id)) as WizardDetection;
        if (!detection.installed) {
          state = 'error';
          error = `${chosen} CLI is not installed on the host`;
          emit();
          return;
        }
        state = 'entering_credential';
      } catch (e) {
        state = 'error';
        error = (e as Error).message ?? 'failed to create backend';
      }
      emit();
    },

    async submitCredential(flowKind, inputs) {
      if (!backend) {
        state = 'error';
        error = 'no backend in progress';
        emit();
        return;
      }
      state = 'validating';
      emit();
      try {
        await opts.client.loginBackend(backend.id, flowKind, inputs);
        backend = (await opts.client.validateBackend(backend.id)) as BackendDTO;
        state = 'done';
      } catch (e) {
        state = 'error';
        error = (e as { message?: string }).message ?? 'validation failed';
      }
      emit();
    },

    reset() {
      state = 'idle';
      kind = undefined;
      detection = undefined;
      backend = undefined;
      error = undefined;
      emit();
    },
  };
}
```

- [ ] **Step 3: Re-export from `src/index.ts`**

```typescript
export { createAccountWizard } from './machines/accountWizard';
export type { AccountWizard, WizardState, WizardDetection } from './machines/accountWizard';
```

- [ ] **Step 4: Run + commit** `feat(ts-core): add accountWizard state machine`

---

## Task 25: vue-headless `useAccountWizard` composable

**Files:**
- Create: `packages/vue-headless/src/useAccountWizard.ts`
- Modify: `packages/vue-headless/src/index.ts`
- Create: `packages/vue-headless/tests/useAccountWizard.test.ts`
- Create: `packages/vue-headless/vitest.config.ts`

- [ ] **Step 1: Write `vitest.config.ts`**

```typescript
import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { environment: 'happy-dom' } });
```

- [ ] **Step 2: Write failing test** using a `defineComponent` harness with `setup(props, { expose })` that calls `useAccountWizard({ client: props.client })`, exposes `wiz`, and the test drives state transitions through `wrapper.vm.wiz` after `mount(Harness, { props: { client } })`. Mock the client methods to return fake success responses. Assert reactive `wiz.state.value` updates through the happy path.

- [ ] **Step 3: Write `src/useAccountWizard.ts`**

```typescript
import { ref, type Ref } from 'vue';
import {
  createAccountWizard,
  type AiAccountsClient,
  type WizardState,
  type WizardDetection,
} from '@ai-accounts/ts-core';

export interface UseAccountWizardOptions {
  client: AiAccountsClient;
  defaultDisplayName?: string;
}

export interface UseAccountWizardReturn {
  state: Ref<WizardState>;
  kind: Ref<string | undefined>;
  detection: Ref<WizardDetection | undefined>;
  backend: Ref<unknown>;
  error: Ref<string | undefined>;
  start: () => void;
  pickKind: (kind: string) => Promise<void>;
  submitCredential: (flowKind: string, inputs: Record<string, string>) => Promise<void>;
  reset: () => void;
}

export function useAccountWizard(options: UseAccountWizardOptions): UseAccountWizardReturn {
  const machine = createAccountWizard({
    client: options.client,
    defaultDisplayName: options.defaultDisplayName,
  });

  const state = ref(machine.state);
  const kind = ref(machine.kind);
  const detection = ref(machine.detection);
  const backend = ref(machine.backend);
  const error = ref(machine.error);

  machine.subscribe(() => {
    state.value = machine.state;
    kind.value = machine.kind;
    detection.value = machine.detection;
    backend.value = machine.backend;
    error.value = machine.error;
  });

  return {
    state, kind, detection, backend, error,
    start: () => machine.start(),
    pickKind: (k) => machine.pickKind(k),
    submitCredential: (fk, inp) => machine.submitCredential(fk, inp),
    reset: () => machine.reset(),
  };
}
```

- [ ] **Step 4: Update `src/index.ts`**

```typescript
export { useAccountWizard } from './useAccountWizard';
export type { UseAccountWizardOptions, UseAccountWizardReturn } from './useAccountWizard';
export const version = '0.0.0';
```

- [ ] **Step 5: Run + commit** `feat(vue-headless): add useAccountWizard composable`

---

## Task 26: vue-styled `<AccountWizard>` component

**Files:**
- Create: `packages/vue-styled/src/styles/tokens.css`
- Create: `packages/vue-styled/src/components/AccountWizard.vue`
- Modify: `packages/vue-styled/src/index.ts`
- Modify: `packages/vue-styled/package.json` (switch to Vite build)
- Create: `packages/vue-styled/vite.config.ts`
- Create: `packages/vue-styled/vitest.config.ts`
- Create: `packages/vue-styled/tests/AccountWizard.test.ts`

- [ ] **Step 1: Write `styles/tokens.css`** with ~40 CSS variables prefixed `--aia-` covering colors (bg, bg-elevated, bg-hover, fg, fg-muted, fg-subtle, border, border-hover, primary, primary-hover, primary-fg, success, warning, danger), radius (sm, base, lg), spacing (1/2/3/4/6/8), typography (font-sans, font-mono, text-xs/sm/base/lg/xl), shadows (sm, base), and transition timing. Defaults form a dark theme (Agented Geist-inspired).

- [ ] **Step 2: Write `src/components/AccountWizard.vue`**

Script section (`<script setup lang="ts">`):
```typescript
import { ref } from 'vue';
import { useAccountWizard, type UseAccountWizardOptions } from '@ai-accounts/vue-headless';

const props = defineProps<{
  client: UseAccountWizardOptions['client'];
  kinds?: Array<{ id: string; display: string }>;
}>();

const emit = defineEmits<{
  done: [backendId: string];
  cancel: [];
}>();

const wiz = useAccountWizard({ client: props.client });
const apiKey = ref('');
const kinds = props.kinds ?? [
  { id: 'claude', display: 'Claude' },
  { id: 'opencode', display: 'OpenCode' },
  { id: 'gemini', display: 'Gemini' },
  { id: 'codex', display: 'Codex' },
];

wiz.start();

async function onPick(kind: string) { await wiz.pickKind(kind); }

async function onSubmit() {
  await wiz.submitCredential('api_key', { api_key: apiKey.value });
  if (wiz.state.value === 'done' && wiz.backend.value) {
    emit('done', (wiz.backend.value as { id: string }).id);
  }
}
```

Template: a `<section class="aia-wizard">` with a header slot, then a `v-if`/`v-else-if` chain keyed on `wiz.state.value` rendering: kind picker (`picking_kind`), "Detecting…" status, credential form with password input (`entering_credential`), "Validating…" status, success slot (`done`), error message with "Try again" button (`error`).

Scoped `<style>` uses only `var(--aia-*)` references for all visual properties. Classes: `.aia-wizard`, `.aia-wizard__header`, `.aia-wizard__kinds`, `.aia-btn`, `.aia-btn--primary`, `.aia-btn--kind`, `.aia-wizard__form`, `.aia-label`, `.aia-input`, `.aia-wizard__status`, `.aia-wizard__success`, `.aia-wizard__error`.

- [ ] **Step 3: Update `src/index.ts`**

```typescript
import './styles/tokens.css';

export { default as AccountWizard } from './components/AccountWizard.vue';
export const version = '0.0.0';
```

- [ ] **Step 4: Update build tooling** — `tsup` does not bundle `.vue`. Switch to Vite:

```
pnpm --filter @ai-accounts/vue-styled add -D vite @vitejs/plugin-vue vue-tsc
```

Update `packages/vue-styled/package.json` scripts:
```json
{
  "scripts": {
    "build": "vite build",
    "test": "vitest run",
    "lint": "eslint src",
    "typecheck": "vue-tsc --noEmit"
  }
}
```

Write `vite.config.ts`:
```typescript
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';

export default defineConfig({
  plugins: [vue()],
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      formats: ['es', 'cjs'],
      fileName: (format) => `index.${format === 'es' ? 'js' : 'cjs'}`,
    },
    rollupOptions: {
      external: ['vue', '@ai-accounts/vue-headless', '@ai-accounts/ts-core'],
      output: { globals: { vue: 'Vue' }, assetFileNames: 'styles.css' },
    },
  },
});
```

Write `vitest.config.ts`:
```typescript
import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  plugins: [vue()],
  test: { environment: 'happy-dom' },
});
```

- [ ] **Step 5: Write `tests/AccountWizard.test.ts`**

```typescript
import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import AccountWizard from '../src/components/AccountWizard.vue';

function makeClient() {
  return {
    createBackend: vi.fn().mockResolvedValue({
      id: 'bkd-1', kind: 'claude', display_name: 'A',
      status: 'unconfigured', config: {},
    }),
    detectBackend: vi.fn().mockResolvedValue({ installed: true }),
    loginBackend: vi.fn().mockResolvedValue({ id: 'bkd-1', status: 'validating' }),
    validateBackend: vi.fn().mockResolvedValue({ id: 'bkd-1', status: 'ready' }),
  } as unknown as Parameters<typeof AccountWizard>[0]['client'];
}

describe('AccountWizard', () => {
  it('renders kind picker initially', () => {
    const wrapper = mount(AccountWizard, { props: { client: makeClient() } });
    expect(wrapper.text()).toContain('Claude');
    expect(wrapper.text()).toContain('OpenCode');
  });

  it('advances through the happy path', async () => {
    const client = makeClient();
    const wrapper = mount(AccountWizard, { props: { client } });
    const claudeBtn = wrapper.findAll('button').find((b) => b.text() === 'Claude');
    await claudeBtn!.trigger('click');
    await new Promise((r) => setTimeout(r, 0));
    expect(wrapper.text()).toContain('API key');
    await wrapper.find('input').setValue('sk-ant-xxx');
    await wrapper.find('form').trigger('submit.prevent');
    await new Promise((r) => setTimeout(r, 0));
    expect(wrapper.text()).toContain('Connected');
    expect(wrapper.emitted('done')).toBeTruthy();
  });
});
```

- [ ] **Step 6: Run + commit** `feat(vue-styled): add AccountWizard component with CSS-var theming`

---

## Task 27: Playground app

**Files:**
- Create: `apps/playground/package.json`, `index.html`, `vite.config.ts`, `src/main.ts`, `src/App.vue`
- Create: `apps/playground/pyproject.toml`, `server.py`
- Modify: root `pyproject.toml` to add `apps/playground` to workspace members

- [ ] **Step 1: Frontend — `package.json`**

```json
{
  "name": "playground",
  "version": "0.0.0",
  "private": true,
  "scripts": { "dev": "vite", "build": "vite build" },
  "dependencies": {
    "vue": "^3.4.0",
    "@ai-accounts/ts-core": "workspace:*",
    "@ai-accounts/vue-headless": "workspace:*",
    "@ai-accounts/vue-styled": "workspace:*"
  },
  "devDependencies": { "vite": "^5.4.0", "@vitejs/plugin-vue": "^5.1.0" }
}
```

- [ ] **Step 2: `vite.config.ts`**

```typescript
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://localhost:20000',
      '/health': 'http://localhost:20000',
      '/schema': 'http://localhost:20000',
    },
  },
});
```

- [ ] **Step 3: `index.html` + `src/main.ts` + `src/App.vue`**

`index.html`:
```html
<!DOCTYPE html>
<html><head><meta charset="UTF-8"/><title>ai-accounts playground</title></head>
<body><div id="app"></div><script type="module" src="/src/main.ts"></script></body></html>
```

`main.ts`:
```typescript
import { createApp } from 'vue';
import App from './App.vue';
createApp(App).mount('#app');
```

`App.vue`:
```vue
<script setup lang="ts">
import { ref } from 'vue';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import { AccountWizard } from '@ai-accounts/vue-styled';

const client = new AiAccountsClient({ baseUrl: '' });
const doneId = ref<string | null>(null);
</script>

<template>
  <main style="max-width: 640px; margin: 40px auto; font-family: system-ui;">
    <h1>ai-accounts playground</h1>
    <AccountWizard :client="client" @done="(id) => (doneId = id)" />
    <p v-if="doneId">Created backend: <code>{{ doneId }}</code></p>
  </main>
</template>
```

- [ ] **Step 4: Backend — `pyproject.toml`**

```toml
[project]
name = "ai-accounts-playground"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = ["ai-accounts-core", "ai-accounts-litestar", "uvicorn"]

[tool.uv.sources]
ai-accounts-core = {workspace = true}
ai-accounts-litestar = {workspace = true}
```

Add `"apps/playground"` to the root `pyproject.toml` workspace members list.

- [ ] **Step 5: `server.py`**

```python
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.backends import ClaudeBackend, OpenCodeBackend
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig

app = create_app(AiAccountsConfig(
    env="development",
    storage=SqliteStorage("./playground.db"),
    vault=EnvKeyVault.from_env(env="development"),
    auth=NoAuth(),
    backends=(ClaudeBackend(), OpenCodeBackend()),
))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=20000)
```

- [ ] **Step 6: End-to-end manual verification**

Terminal 1: `cd ~/Developer/Projects/ai-accounts && uv run python apps/playground/server.py`
Terminal 2: `pnpm --filter playground dev`

Open `http://localhost:5173`. The AccountWizard should render. Click "Claude" — it creates a backend and runs detect (outcome depends on whether `claude` is installed). Enter a test API key — validate will fail (expected, key is fake); confirm the error state shows with "Try again".

- [ ] **Step 7: Commit** `feat(playground): add demo Litestar server and Vue app`

---

## Task 28: Changeset + version bump to 0.1.0

- [ ] **Step 1: Add a changeset** — `pnpm changeset add`, select all three JS packages, bump minor, message: `"First public preview: account management, Claude + OpenCode backends, themeable Vue wizard."`

- [ ] **Step 2: Version bump** — `pnpm changeset version` updates the three JS packages to 0.1.0.

- [ ] **Step 3: Manually bump Python versions**

```
packages/core/pyproject.toml                              version = "0.1.0"
packages/litestar/pyproject.toml                          version = "0.1.0"
packages/core/src/ai_accounts_core/__init__.py            __version__ = "0.1.0"
packages/litestar/src/ai_accounts_litestar/__init__.py    __version__ = "0.1.0"
```

- [ ] **Step 4: Re-run codegen + full tests**

```
just codegen
just test
git diff --exit-code
```

- [ ] **Step 5: Commit + tag (do not push tag until Part C lands)**

```
git add -A
git commit -m "release: bump all packages to 0.1.0"
git tag v0.1.0
```

---

**Phase 1 package work complete.** Proceed to Part C for Agented integration.

---

# Part C — Agented Integration

All Part C tasks happen in a dedicated worktree of the Agented repo, NOT in the `ai-accounts` repo and NOT on Agented's `main` branch.

## Task 29: Create Agented worktree

- [ ] **Step 1: Create worktree off Agented main**

```
cd ~/Developer/Projects/Agented
git fetch origin
git worktree add ../Agented-ai-accounts-migration -b feat/ai-accounts-phase-1 main
cd ../Agented-ai-accounts-migration
git branch --show-current
```

Expected output: `feat/ai-accounts-phase-1`

- [ ] **Step 2: Verify main is untouched**

```
cd ~/Developer/Projects/Agented
git status
git log -1 --oneline
```

All subsequent Part C tasks happen inside `~/Developer/Projects/Agented-ai-accounts-migration`.

---

## Task 30: Install ai-accounts packages into Agented (editable / file: protocol)

**Files (worktree):**
- Modify: `backend/pyproject.toml`
- Modify: `frontend/package.json`

- [ ] **Step 1: Build the ai-accounts JS packages first**

```
cd ~/Developer/Projects/ai-accounts
pnpm -r build
```

This must produce `packages/*/dist/` directories that Agented's frontend will consume.

- [ ] **Step 2: Install Python packages as editable local paths**

```
cd ~/Developer/Projects/Agented-ai-accounts-migration/backend
uv add --editable ~/Developer/Projects/ai-accounts/packages/core
uv add --editable ~/Developer/Projects/ai-accounts/packages/litestar
uv run python -c "from ai_accounts_litestar.app import create_app; print('ok')"
```

- [ ] **Step 3: Install JS packages via `file:` protocol**

```
cd ~/Developer/Projects/Agented-ai-accounts-migration/frontend
npm install --save file:../../ai-accounts/packages/ts-core \
                    file:../../ai-accounts/packages/vue-headless \
                    file:../../ai-accounts/packages/vue-styled
```

Verify `frontend/node_modules/@ai-accounts/ts-core/dist/index.js` exists.

- [ ] **Step 4: Commit**

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
git add backend/pyproject.toml backend/uv.lock frontend/package.json frontend/package-lock.json
git commit -m "chore: install ai-accounts@0.1.0 packages for dogfood migration"
```

---

## Task 31: Run Litestar as a separate process on port 20001

**Decision:** Rather than bridge Flask↔ASGI in a single process, run the two stacks as separate processes and let the frontend dev proxy route `/api/v1/*` to port 20001 while Agented's existing routes stay on port 20000. Simpler, lower blast radius.

**Files:**
- Create: `backend/scripts/run_ai_accounts.py`
- Modify: `justfile`
- Modify: `frontend/vite.config.ts`

- [ ] **Step 1: Write `backend/scripts/run_ai_accounts.py`**

```python
"""Run the ai-accounts Litestar app alongside Agented's Flask backend.

Listens on port 20001. The Vite dev server and any production reverse proxy
route /api/v1/* to this process.
"""

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.backends import ClaudeBackend, OpenCodeBackend
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig

app = create_app(AiAccountsConfig(
    env="development",
    storage=SqliteStorage("./ai_accounts.db"),
    vault=EnvKeyVault.from_env(env="development"),
    auth=NoAuth(),
    backends=(ClaudeBackend(), OpenCodeBackend()),
))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=20001)
```

- [ ] **Step 2: Extend `justfile`**

```makefile
dev-ai-accounts:
    cd backend && uv run python scripts/run_ai_accounts.py

dev-all:
    just kill
    just dev-backend & just dev-ai-accounts & just dev-frontend & wait
```

- [ ] **Step 3: Update `frontend/vite.config.ts` proxy** — insert `/api/v1` BEFORE `/api` in the proxy block (order matters — more specific first):

```typescript
server: {
  proxy: {
    '/api/v1': { target: 'http://localhost:20001', changeOrigin: true },
    '/api': 'http://localhost:20000',
    '/admin': 'http://localhost:20000',
    '/health': 'http://localhost:20000',
    '/docs': 'http://localhost:20000',
    '/openapi': 'http://localhost:20000',
  },
},
```

- [ ] **Step 4: Smoke test** — in three terminals: `just dev-backend`, `just dev-ai-accounts`, `just dev-frontend`. Then:

```
curl http://localhost:3000/api/v1/backends
```

Expected: `{"items":[]}` (proxied to :20001).

```
curl http://localhost:3000/api/bots
```

Expected: Agented's existing response (proxied to :20000).

- [ ] **Step 5: Commit** `feat: mount ai-accounts Litestar app on port 20001 alongside Flask`

---

## Task 32: Swap AccountWizard.vue for the package component

**Files:**
- Audit: all files in `frontend/src` that import `components/backends/AccountWizard.vue`.
- Modify call sites.
- Delete: `frontend/src/components/backends/AccountWizard.vue`

- [ ] **Step 1: Find current usages**

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
grep -rn "components/backends/AccountWizard" frontend/src
grep -rn "from.*AccountWizard" frontend/src
```

- [ ] **Step 2: Replace imports at each call site**

Before:
```typescript
import AccountWizard from '@/components/backends/AccountWizard.vue'
```

After:
```typescript
import { AccountWizard } from '@ai-accounts/vue-styled'
import { AiAccountsClient } from '@ai-accounts/ts-core'
import '@ai-accounts/vue-styled/styles.css'
```

Wire a client instance in the `<script setup>`:
```typescript
const client = new AiAccountsClient({ baseUrl: '' })
```

Update template usage to match the new component's props/events:
```vue
<AccountWizard :client="client" @done="handleWizardDone" />
```

- [ ] **Step 3: Run frontend tests**

```
cd frontend && npm run test:run
```

Any tests that referenced the old component must be updated to mount the new one with a mocked client, or removed if they tested implementation details.

- [ ] **Step 4: Delete the old component**

```
rm frontend/src/components/backends/AccountWizard.vue
grep -rn "components/backends/AccountWizard" frontend/
```

The grep should return no matches.

- [ ] **Step 5: Full verification**

```
just build
```

Expected: vue-tsc + vite build succeed with 0 errors.

- [ ] **Step 6: Commit** `feat(frontend): swap AccountWizard.vue for @ai-accounts/vue-styled component`

---

## Task 33: Delete superseded Agented backend CRUD routes

**Files to audit:**
- `backend/app/routes/backends.py`
- `backend/app/services/backend_service.py`

- [ ] **Step 1: Audit the old routes**

```
grep -n "APIBlueprint\|@.*route\|@.*get\|@.*post" backend/app/routes/backends.py
```

Identify routes superseded by `/api/v1/backends` (CRUD + detect + login + validate). Keep any routes that interact with bots, teams, executions, or features not in Phase 1 scope.

- [ ] **Step 2: Remove superseded handler functions**

Delete each superseded handler from `backend/app/routes/backends.py`. If the file becomes empty, delete it and remove its registration from `backend/app/__init__.py`.

- [ ] **Step 3: Remove orphaned service code**

```
grep -rn "from app.services.backend_service import" backend/
```

If the only remaining imports reference functions you just removed, delete `backend_service.py`. If any non-Phase-1 code still imports from it, leave the file but delete the unused functions.

- [ ] **Step 4: Run backend tests**

```
cd backend && uv run pytest
```

Delete tests that exercised the removed routes. Any unrelated test must still pass.

- [ ] **Step 5: Manual smoke test**

```
just dev-all
```

In the browser: navigate to the page that showed the account wizard. Click through it end to end. Confirm:
1. The new themed wizard renders.
2. The created backend is visible via `curl http://localhost:3000/api/v1/backends`.
3. No console errors on any page.
4. Features outside Phase 1 scope (bots, workflows, etc.) still work.

- [ ] **Step 6: Commit** `feat: delete Agented backend CRUD (superseded by @ai-accounts/litestar)`

---

## Task 34: Remove `backendApi` from frontend API service

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Find usages**

```
grep -rn "backendApi\." frontend/src
```

- [ ] **Step 2: Replace each call site** with the equivalent `AiAccountsClient` method:

| Old | New |
|---|---|
| `backendApi.list()` | `client.listBackends()` (returns `{items: ...}`) |
| `backendApi.create(...)` | `client.createBackend(...)` |
| `backendApi.get(id)` | `client.getBackend(id)` |
| `backendApi.delete(id)` | `client.deleteBackend(id)` |
| `backendApi.detect(id)` | `client.detectBackend(id)` |
| `backendApi.login(id, ...)` | `client.loginBackend(id, flow, inputs)` |
| `backendApi.validate(id)` | `client.validateBackend(id)` |

Provide a shared `client` via `provide`/`inject` or a module-level singleton — match whatever convention Agented uses for other domain APIs.

- [ ] **Step 3: Delete `backendApi` from `api.ts`**

Keep every other domain API object. Don't remove unrelated code.

- [ ] **Step 4: Verify**

```
cd frontend && npm run test:run
just build
```

- [ ] **Step 5: Commit** `refactor(frontend): remove backendApi (use @ai-accounts/ts-core client)`

---

## Task 35: Integration smoke test in Agented's test suite

**Files:**
- Create: `backend/tests/integration/test_ai_accounts_proxy.py`

- [ ] **Step 1: Write ASGI in-process smoke test** — spins up the Litestar app via its callable and uses `httpx.ASGITransport` to hit `/api/v1/backends` and `/health` without opening a real port.

```python
import pytest
from httpx import ASGITransport, AsyncClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.backends import ClaudeBackend, OpenCodeBackend
from ai_accounts_core.testing import FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest.fixture
async def client(tmp_path):
    app = create_app(AiAccountsConfig(
        env="development",
        storage=SqliteStorage(str(tmp_path / "t.db")),
        vault=FakeVault(),
        auth=NoAuth(),
        backends=(ClaudeBackend(), OpenCodeBackend()),
    ))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_backends_empty(client):
    response = await client.get("/api/v1/backends")
    assert response.status_code == 200
    assert response.json() == {"items": []}


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
```

- [ ] **Step 2: Run + commit** `test(integration): smoke test mounted ai-accounts Litestar app`

---

## Task 36: Final verification, merge, release

- [ ] **Step 1: Full verification in the worktree**

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
just build
cd backend && uv run pytest
cd ../frontend && npm run test:run
```

All three must pass with 0 failures.

- [ ] **Step 2: Manual UI verification**

Run `just dev-all`. Walk through the account wizard in the browser against a real CLI if available (otherwise confirm error states work). Verify:
- Wizard renders with the new themed component.
- create → detect → enter credential → validate happy path succeeds when the CLI is installed.
- Created backend persists across a stack restart.
- Features outside the package scope (bots, executions, workflows, etc.) are unchanged.
- No console errors or 404s.

- [ ] **Step 3: Merge into Agented main**

```
cd ~/Developer/Projects/Agented
git fetch origin
git merge --no-ff feat/ai-accounts-phase-1 -m "feat: integrate ai-accounts@0.1.0 (Phase 1)"
git push origin main
```

- [ ] **Step 4: Publish ai-accounts packages**

```
cd ~/Developer/Projects/ai-accounts
git push origin main
git push origin v0.1.0
pnpm changeset publish
# Python packages:
cd packages/core && uv build && uv publish
cd ../litestar && uv build && uv publish
```

Verify on npmjs.com and PyPI that all five packages show `0.1.0`.

- [ ] **Step 5: Clean up the worktree**

```
cd ~/Developer/Projects/Agented
git worktree remove ../Agented-ai-accounts-migration
git branch -d feat/ai-accounts-phase-1
```

- [ ] **Step 6: Follow-up PR — switch Agented from local paths to published versions**

```
cd ~/Developer/Projects/Agented/backend
uv remove ai-accounts-core ai-accounts-litestar
uv add "ai-accounts-core==0.1.0" "ai-accounts-litestar==0.1.0"

cd ../frontend
npm uninstall @ai-accounts/ts-core @ai-accounts/vue-headless @ai-accounts/vue-styled
npm install @ai-accounts/ts-core@0.1.0 @ai-accounts/vue-headless@0.1.0 @ai-accounts/vue-styled@0.1.0
```

Open a PR, verify CI green, merge.

---

**Phase 0 + Phase 1 complete.** `ai-accounts@0.1.0` is shipping. Agented dogfoods the new account management flow via the Vue wizard.

Next plan (written when this one is verified green): **Phase 2 — onboarding + remaining backends (Gemini, Codex)**.

## Success criteria

- ✅ `ai-accounts` repo exists, CI green on main
- ✅ `ai-accounts-core` and `ai-accounts-litestar` published to PyPI at 0.1.0
- ✅ `@ai-accounts/ts-core`, `@ai-accounts/vue-headless`, `@ai-accounts/vue-styled` published to npm at 0.1.0
- ✅ Storage, Vault, Auth, Backend, Transport Protocols defined and documented
- ✅ FakeStorage, FakeVault, FakeBackend, FakeAuth shipped in `ai_accounts_core.testing`
- ✅ Storage and Vault conformance suites shipped and pass against Fake + real adapters
- ✅ SqliteStorage, EnvKeyVault, NoAuth, ApiKeyAuth adapters
- ✅ ClaudeBackend and OpenCodeBackend (detect + login + validate + list_models)
- ✅ Litestar `/api/v1/backends` routes with production-mode startup guard
- ✅ Vue AccountWizard component themeable via `--aia-*` CSS vars
- ✅ Agented consumes the package via mounted Litestar on port 20001, no regressions in existing features
- ✅ Agented `backend_service.py` CRUD and `AccountWizard.vue` removed

## Explicitly NOT in 0.1.0 (deferred to later phases)

- ❌ No OIDC / SSO (Phase 5)
- ❌ No chat, PTY, or sessions (Phases 3–4)
- ❌ No onboarding wizard (Phase 2)
- ❌ No KMS vault or keychain (Phase 6+)
- ❌ No React/Svelte frontend
- ❌ SqliteStorage only; no Postgres adapter yet
- ❌ Credential rotation not implemented
