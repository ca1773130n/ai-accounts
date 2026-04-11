import base64
import logging

import pytest

from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.protocols.vault import VaultError
from ai_accounts_core.testing import run_vault_conformance


@pytest.mark.asyncio
async def test_env_key_vault_conformance(monkeypatch):
    key_b64 = base64.b64encode(b"\x00" * 32).decode()
    monkeypatch.setenv("AI_ACCOUNTS_VAULT_KEY", key_b64)
    vault = EnvKeyVault.from_env()
    await run_vault_conformance(vault)


def test_production_mode_refuses_derived_key(monkeypatch):
    monkeypatch.delenv("AI_ACCOUNTS_VAULT_KEY", raising=False)
    with pytest.raises(RuntimeError, match="vault key"):
        EnvKeyVault.from_env(env="production")


@pytest.mark.asyncio
async def test_dev_mode_derives_key_with_warning(monkeypatch, caplog):
    monkeypatch.delenv("AI_ACCOUNTS_VAULT_KEY", raising=False)
    caplog.set_level(logging.WARNING)
    vault = EnvKeyVault.from_env(env="development")
    assert any("dev" in rec.message.lower() for rec in caplog.records)
    ct = await vault.encrypt(b"hi", context={"k": "v"})
    assert await vault.decrypt(ct, context={"k": "v"}) == b"hi"


def test_wrong_key_length_rejected(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_VAULT_KEY", base64.b64encode(b"\x00" * 16).decode())
    with pytest.raises(RuntimeError, match="32 bytes"):
        EnvKeyVault.from_env()


def test_invalid_base64_rejected(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_VAULT_KEY", "!!! not base64 !!!")
    with pytest.raises(RuntimeError, match="base64"):
        EnvKeyVault.from_env()


@pytest.mark.asyncio
async def test_unknown_envelope_version_rejected(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_VAULT_KEY", base64.b64encode(b"\x00" * 32).decode())
    vault = EnvKeyVault.from_env()
    ct = await vault.encrypt(b"payload", context={"k": "v"})
    # Flip the version byte to an unknown value
    tampered = bytes([0xFF]) + ct[1:]
    with pytest.raises(VaultError, match="envelope"):
        await vault.decrypt(tampered, context={"k": "v"})


def test_rotate_not_implemented(monkeypatch):
    import asyncio
    monkeypatch.setenv("AI_ACCOUNTS_VAULT_KEY", base64.b64encode(b"\x00" * 32).decode())
    vault = EnvKeyVault.from_env()
    with pytest.raises(NotImplementedError):
        asyncio.run(vault.rotate("old-key-id"))
