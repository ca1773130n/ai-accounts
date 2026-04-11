import json
from typing import Protocol, runtime_checkable


class VaultError(Exception):
    """Raised when a vault operation fails (key missing, tamper, etc.)."""


def canonicalize_vault_context(context: dict[str, str]) -> bytes:
    """Canonical, injective encoding of a vault binding context for AAD.

    Any VaultProtocol implementation that binds ciphertext to a context MUST
    use this encoding, otherwise different contexts can hash-collide and
    bypass binding. Uses canonical JSON of sorted items for injectivity:
    JSON escapes `"` and control chars, and the sorted-list structure
    ensures {"a": "b"} vs {"b": "a"} produce different bytes.
    """
    return json.dumps(
        sorted(context.items()),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@runtime_checkable
class VaultProtocol(Protocol):
    async def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> bytes: ...
    async def decrypt(self, ciphertext: bytes, *, context: dict[str, str]) -> bytes: ...
    async def current_key_id(self) -> str: ...
    async def rotate(self, old_key_id: str) -> None: ...
