"""Backend metadata registry — aggregated and served at /_meta."""

from __future__ import annotations

from ai_accounts_core.metadata.types import BackendMetadata


class BackendRegistry:
    def __init__(self) -> None:
        self._by_kind: dict[str, BackendMetadata] = {}

    def register(self, meta: BackendMetadata) -> None:
        if meta.kind in self._by_kind:
            raise ValueError(f"backend kind '{meta.kind}' already registered")
        self._by_kind[meta.kind] = meta

    def get(self, kind: str) -> BackendMetadata:
        return self._by_kind[kind]

    def list(self) -> list[BackendMetadata]:
        return list(self._by_kind.values())
