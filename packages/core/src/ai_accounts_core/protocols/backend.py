from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

import msgspec

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.domain.chat import ChatMessage
from ai_accounts_core.domain.usage import UsageWindow
from ai_accounts_core.login import LoginSession
from ai_accounts_core.metadata import BackendMetadata


class Model(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    display_name: str
    context_window: int | None = None
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None


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
    # `read` is an async generator: it RETURNS an AsyncIterator[bytes], it is not
    # a coroutine. The sole caller (routes/pty_ws.py) consumes it with
    # `async for chunk in handle.read()`, so the signature must not be `async def`
    # (which would type the return as Coroutine[..., AsyncIterator[bytes]]).
    def read(self) -> AsyncIterator[bytes]: ...
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
        config: dict[str, object],
        vault_ctx: dict[str, object],
        isolation_dir: Path,
    ) -> LoginSession: ...
    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool: ...
    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]: ...
    # `chat` is an async generator: calling it RETURNS an AsyncIterator, it is
    # not itself a coroutine. Callers consume it with `async for ev in
    # impl.chat(...)`, so (like `PtyHandle.read` above) the signature must be a
    # plain `def` — `async def` would type the return as Coroutine[..., Async-
    # Iterator[...]] and break every `async for` call site.
    def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]: ...
    async def get_usage(
        self,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> list[UsageWindow]: ...
    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle: ...
