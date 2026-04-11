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
