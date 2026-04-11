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
