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
