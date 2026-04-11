from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ai_accounts_core.protocols.vault import VaultError, canonicalize_vault_context

log = logging.getLogger(__name__)

_ENVELOPE_VERSION = 1
_NONCE_LEN = 12
_KEY_ID = "envkey://v1"


class EnvKeyVault:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("EnvKeyVault requires a 32-byte (AES-256) key")
        self._aesgcm = AESGCM(key)

    @classmethod
    def from_env(
        cls,
        *,
        env: Literal["development", "production"] = "development",
        env_var: str = "AI_ACCOUNTS_VAULT_KEY",
    ) -> "EnvKeyVault":
        raw = os.environ.get(env_var)
        if raw:
            try:
                key = base64.b64decode(raw, validate=True)
            except Exception as exc:
                raise RuntimeError(f"{env_var} is not valid base64") from exc
            if len(key) != 32:
                raise RuntimeError(
                    f"{env_var} must decode to 32 bytes (AES-256), got {len(key)}"
                )
            return cls(key)

        if env == "production":
            raise RuntimeError(
                "ai-accounts refuses to start in production without a vault key. "
                f"Set {env_var} to a base64-encoded 32-byte key."
            )

        log.warning(
            "ai-accounts: no %s set, deriving a dev-only fallback vault key. "
            "DO NOT use this in production.",
            env_var,
        )
        fallback_seed = b"ai-accounts-dev-insecure-fallback-seed-v1"
        derived = hashlib.sha256(fallback_seed).digest()
        return cls(derived)

    async def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        aad = canonicalize_vault_context(context)
        ct = self._aesgcm.encrypt(nonce, plaintext, aad)
        return bytes([_ENVELOPE_VERSION]) + nonce + ct

    async def decrypt(self, ciphertext: bytes, *, context: dict[str, str]) -> bytes:
        if len(ciphertext) < 1 + _NONCE_LEN + 16:
            raise VaultError("ciphertext too short")
        if ciphertext[0] != _ENVELOPE_VERSION:
            raise VaultError(f"unknown vault envelope version {ciphertext[0]}")
        nonce = ciphertext[1 : 1 + _NONCE_LEN]
        ct = ciphertext[1 + _NONCE_LEN :]
        aad = canonicalize_vault_context(context)
        try:
            return self._aesgcm.decrypt(nonce, ct, aad)
        except InvalidTag as exc:
            raise VaultError(
                "vault decryption failed (tamper, wrong context, or wrong key)"
            ) from exc

    async def current_key_id(self) -> str:
        return _KEY_ID

    async def rotate(self, old_key_id: str) -> None:
        raise NotImplementedError("EnvKeyVault rotation not supported in v0.1")
