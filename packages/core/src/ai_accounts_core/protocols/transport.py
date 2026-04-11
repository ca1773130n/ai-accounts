from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from ai_accounts_core.protocol.wire import WireEvent


@runtime_checkable
class TransportProtocol(Protocol):
    async def send(self, event: WireEvent) -> None: ...
    def receive(self) -> AsyncIterator[WireEvent]: ...
    async def close(self) -> None: ...
