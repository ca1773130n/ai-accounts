from __future__ import annotations

import msgspec
from ai_accounts_core.domain.backend import Backend, DetectResult


class BackendDTO(msgspec.Struct, kw_only=True):
    id: str
    kind: str
    display_name: str
    status: str
    config: dict[str, object]
    config_dir: str | None = None
    last_error: str | None = None

    @classmethod
    def from_domain(cls, backend: Backend, config_dir: str | None = None) -> BackendDTO:
        return cls(
            id=backend.id,
            kind=backend.kind,
            display_name=backend.display_name,
            status=backend.status.value,
            config=backend.config,
            config_dir=config_dir,
            last_error=backend.last_error,
        )


class BackendListDTO(msgspec.Struct, kw_only=True):
    items: list[BackendDTO]


class CreateBackendRequest(msgspec.Struct, kw_only=True):
    kind: str
    display_name: str
    config: dict[str, object] = {}


class UpdateBackendRequest(msgspec.Struct, kw_only=True):
    display_name: str | None = None
    config: dict[str, object] | None = None


class DetectResultDTO(msgspec.Struct, kw_only=True):
    installed: bool
    version: str | None = None
    path: str | None = None
    notes: str | None = None

    @classmethod
    def from_domain(cls, r: DetectResult) -> DetectResultDTO:
        return cls(installed=r.installed, version=r.version, path=r.path, notes=r.notes)


class OnboardingStateDTO(msgspec.Struct, kw_only=True):
    id: str
    current_step: str
    selected_backend_kind: str | None = None
    created_backend_id: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, state: object) -> OnboardingStateDTO:
        from ai_accounts_core.domain.onboarding import OnboardingState

        assert isinstance(state, OnboardingState)
        return cls(
            id=state.id,
            current_step=state.current_step.value,
            selected_backend_kind=state.selected_backend_kind,
            created_backend_id=state.created_backend_id,
            error=state.error,
        )


class PickKindRequest(msgspec.Struct, kw_only=True):
    kind: str
    display_name: str


class DetectResultsDTO(msgspec.Struct, kw_only=True):
    results: dict[str, DetectResultDTO]
