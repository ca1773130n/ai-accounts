from collections.abc import AsyncIterator
from typing import ClassVar, Protocol, runtime_checkable

import msgspec

from ai_accounts_core.domain.backend import DetectResult
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
