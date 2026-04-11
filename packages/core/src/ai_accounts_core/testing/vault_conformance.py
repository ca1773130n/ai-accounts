"""Shared conformance suite for VaultProtocol implementations."""

import pytest

from ai_accounts_core.protocols.vault import VaultError, VaultProtocol


async def run_vault_conformance(vault: VaultProtocol) -> None:
    await _roundtrip(vault)
    await _context_binding(vault)
    await _tamper_detection(vault)
    await _key_id_exposed(vault)


async def _roundtrip(vault: VaultProtocol) -> None:
    plaintext = b"super-secret-api-key-abc123"
    ct = await vault.encrypt(plaintext, context={"backend_id": "bkd-1"})
    pt = await vault.decrypt(ct, context={"backend_id": "bkd-1"})
    assert pt == plaintext


async def _context_binding(vault: VaultProtocol) -> None:
    ct = await vault.encrypt(b"x", context={"backend_id": "bkd-A"})
    with pytest.raises(VaultError):
        await vault.decrypt(ct, context={"backend_id": "bkd-B"})


async def _tamper_detection(vault: VaultProtocol) -> None:
    ct = bytearray(await vault.encrypt(b"payload", context={"backend_id": "bkd-1"}))
    ct[-1] ^= 0xFF
    with pytest.raises(VaultError):
        await vault.decrypt(bytes(ct), context={"backend_id": "bkd-1"})


async def _key_id_exposed(vault: VaultProtocol) -> None:
    key_id = await vault.current_key_id()
    assert isinstance(key_id, str) and key_id
