from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Protocol, Union, runtime_checkable

import msgspec

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.domain.chat import ChatMessage
from ai_accounts_core.login import LoginSession
from ai_accounts_core.metadata import BackendMetadata


class Model(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    display_name: str
    context_window: int | None = None
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None


class LoginFlow(msgspec.Struct, frozen=True, kw_only=True):
    kind: str  # "api_key" | "oauth_device" | ...
    inputs: dict[str, str] = {}


class CredentialLogin(
    msgspec.Struct, tag="credential", tag_field="type", frozen=True, kw_only=True
):
    credential: bytes


class OAuthDeviceLogin(
    msgspec.Struct, tag="oauth_device", tag_field="type", frozen=True, kw_only=True
):
    verification_uri: str
    user_code: str
    expires_at: datetime
    handle: str


class LoginError(
    msgspec.Struct, tag="error", tag_field="type", frozen=True, kw_only=True
):
    code: str
    message: str


LoginResult = Union[CredentialLogin, OAuthDeviceLogin, LoginError]


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
    supported_login_flows: ClassVar[frozenset[str]]
    metadata: ClassVar[BackendMetadata]

    async def detect(self) -> DetectResult: ...
    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession: ...
    async def login(self, flow: LoginFlow, *, isolation_dir: Path) -> LoginResult: ...
    async def poll_login(self, handle: str, *, isolation_dir: Path) -> LoginResult: ...
    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool: ...
    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]: ...
    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]: ...
    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle: ...
