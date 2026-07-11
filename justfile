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

# ── Playground ──────────────────────────────────────────────────────────
# Start the playground end-to-end: Litestar sidecar API on AIA_HOST:AIA_PORT
# (default 127.0.0.1:30000) AND the Vite dev server on its configured port
# (6173 — see apps/playground/vite.config.ts, strictPort: true). Both run in
# foreground via `concurrently`; Ctrl-C stops both.
#
#   just playground                      # 127.0.0.1:30000 (only this machine)
#   just playground 0.0.0.0              # all interfaces — accessible over LAN/DDNS
#   just playground 0.0.0.0 8080         # custom API port (also update vite proxy)
#
# PORT may NOT be 6173 — that's the Vite port. Passing 6173 here would cause
# both processes to fight for the socket. The recipe rejects it upfront.
#
# Before starting, any existing listener on the chosen API port AND on 6173
# is killed (TERM, then KILL after 500 ms) so a leftover from a previous
# `just playground` (Ctrl-C didn't reap it, crashed, etc.) doesn't block
# the new run with EADDRINUSE.
#
# Arg defaults are inlined into the env so a bare `just playground` matches
# what server.py would do without any AIA_* env set.
playground HOST="127.0.0.1" PORT="30000":
    @if [ "{{PORT}}" = "6173" ]; then \
        echo ""; \
        echo "  6173 is the Vite port (the URL your browser hits) — NOT the API port."; \
        echo ""; \
        echo "  The PORT arg sets the Python API's listen port (default 30000)."; \
        echo "  Vite always runs on 6173 and proxies /api/*, /health, /schema"; \
        echo "  to the API. Vite already binds 0.0.0.0 in vite.config.ts."; \
        echo ""; \
        echo "  You probably want:"; \
        echo "    just playground 0.0.0.0"; \
        echo ""; \
        echo "  → API on 127.0.0.1:30000, Vite on 0.0.0.0:6173"; \
        echo "  → open http://<this-host>:6173/ from any machine that can reach it"; \
        echo ""; \
        exit 1; \
    fi
    @{{justfile_directory()}}/scripts/kill-port.sh {{PORT}} 6173
    AIA_HOST={{HOST}} AIA_PORT={{PORT}} pnpm --filter playground start

# Build a production bundle of the playground frontend (just the Vue app —
# the Python API is always run from source). Output: apps/playground/dist/.
playground-build:
    pnpm --filter playground build

# API only — no Vite — for hosts that serve their own pre-built frontend
# or want to point a different UI at the API. Same pre-flight kill logic.
playground-api HOST="127.0.0.1" PORT="30000":
    @{{justfile_directory()}}/scripts/kill-port.sh {{PORT}}
    AIA_HOST={{HOST}} AIA_PORT={{PORT}} pnpm --filter playground server

clean:
    rm -rf packages/*/dist packages/*/.turbo
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

# ── Release ──────────────────────────────────────────────────────────────
# `just bump 0.3.10` updates every published package's version (JS package.json,
# Python pyproject.toml) AND the source `version` constants in vue-styled /
# vue-headless. Run before `just release`.
bump VERSION:
    @echo "Bumping all packages to {{VERSION}}…"
    sed -i.bak 's/^version = "[0-9.]*"/version = "{{VERSION}}"/' packages/core/pyproject.toml packages/litestar/pyproject.toml
    @for f in packages/ts-core/package.json packages/vue-headless/package.json packages/vue-styled/package.json packages/council-cli/package.json; do \
        sed -i.bak 's/"version": "[0-9.]*"/"version": "{{VERSION}}"/' "$f"; \
    done
    sed -i.bak "s/version = '[0-9.]*'/version = '{{VERSION}}'/" packages/vue-styled/src/index.ts packages/vue-headless/src/index.ts
    rm -f packages/*/pyproject.toml.bak packages/*/package.json.bak packages/*/src/index.ts.bak
    @# --all-packages matches CI: bare `uv sync` prunes to the root project's
    @# deps (removing litestar etc.), which the old with-deps editable
    @# re-link below silently repaired — the --no-deps one does not.
    uv sync --all-extras --all-packages
    @# `uv sync` resolves the lock but does NOT re-link the editable workspace
    @# packages to the bumped pyproject.toml. Without this step the next
    @# `uv run pytest` (and `just release`) sees stale dist-info and fails
    @# collection with ModuleNotFoundError: ai_accounts_core. Force the
    @# re-link explicitly so the release pipeline is reproducible.
    @# --no-deps is load-bearing: without it this resolves dependencies FRESH,
    @# silently upgrading litestar/msgspec past uv.lock in the local venv —
    @# which made locally-regenerated codegen artifacts diverge from CI's
    @# locked regeneration (the v0.4.5-0.4.7 codegen CI failures).
    uv pip install --no-deps -e packages/core -e packages/litestar
    @echo "Bumped. Verify with: git diff -- packages apps"

# `just release VERSION` runs the full ship sequence:
#   tests → build → tag → push → npm publish → PyPI publish.
# Assumes you've already run `just bump VERSION`, committed, and merged to main.
# Needs $PYPI_TOKEN in the invoking shell (exported from ~/.zshrc).
release VERSION:
    @echo "Releasing v{{VERSION}}…"
    @# Bail if the working tree is dirty — releases must be from a clean main.
    @test -z "$(git status --porcelain)" || (echo "ERROR: working tree dirty. Commit or stash first." && exit 1)
    @test "$(git rev-parse --abbrev-ref HEAD)" = "main" || (echo "ERROR: not on main." && exit 1)
    @# Check PyPI auth up front — failing after the npm publish would leave a
    @# half-shipped release (npm at VERSION, PyPI behind).
    @test -n "$PYPI_TOKEN" || (echo "ERROR: PYPI_TOKEN not set — run from a shell that sources ~/.zshrc." && exit 1)
    just build   # build first so JS tests can resolve workspace package entries (ts-core/dist/index.js etc.)
    just test
    git tag -a v{{VERSION}} -m "v{{VERSION}}"
    git push origin main
    git push origin v{{VERSION}}
    pnpm publish -r --access public --no-git-checks
    uv build --package ai-accounts-core
    uv build --package ai-accounts-litestar
    uv publish --token "$PYPI_TOKEN" dist/ai_accounts_core-{{VERSION}}* dist/ai_accounts_litestar-{{VERSION}}*
    @echo "Released v{{VERSION}}. Verify on npm:"
    @for pkg in @ai-accounts/ts-core @ai-accounts/vue-headless @ai-accounts/vue-styled @ai-accounts/council; do \
        printf '  %s latest: ' "$pkg"; npm view "$pkg" version; \
    done
    @echo "And on PyPI:"
    @echo "  https://pypi.org/project/ai-accounts-core/{{VERSION}}/"
    @echo "  https://pypi.org/project/ai-accounts-litestar/{{VERSION}}/"
