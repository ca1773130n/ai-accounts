from __future__ import annotations

from datetime import datetime
from typing import Literal

import msgspec

from ai_accounts_core.domain.backend import Backend, DetectResult


class BackendDTO(msgspec.Struct, kw_only=True):
    id: str
    kind: str
    display_name: str
    status: str
    config: dict[str, object]
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
    config: dict[str, object] = {}


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


class OAuthDeviceLoginDTO(msgspec.Struct, kw_only=True):
    verification_uri: str
    user_code: str
    expires_at: datetime
    handle: str


class LoginResponseDTO(msgspec.Struct, kw_only=True):
    kind: Literal["complete", "pending"]
    backend: BackendDTO | None = None
    oauth: OAuthDeviceLoginDTO | None = None

    @classmethod
    def from_service(cls, response: object) -> "LoginResponseDTO":
        from ai_accounts_core.services.accounts import LoginResponse

        assert isinstance(response, LoginResponse)
        backend_dto = BackendDTO.from_domain(response.backend) if response.backend else None
        oauth_dto = None
        if response.oauth is not None:
            oauth_dto = OAuthDeviceLoginDTO(
                verification_uri=response.oauth.verification_uri,
                user_code=response.oauth.user_code,
                expires_at=response.oauth.expires_at,
                handle=response.oauth.handle,
            )
        return cls(kind=response.kind, backend=backend_dto, oauth=oauth_dto)


class PollLoginRequest(msgspec.Struct, kw_only=True):
    handle: str


class OnboardingStateDTO(msgspec.Struct, kw_only=True):
    id: str
    current_step: str
    selected_backend_kind: str | None = None
    created_backend_id: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, state: object) -> "OnboardingStateDTO":
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
