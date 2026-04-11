import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits


def new_id(prefix: str, length: int = 12) -> str:
    """Generate a prefixed random ID like 'bkd-ab3fg9h1k2l0'.

    Uses the system CSPRNG (secrets.choice). Alphabet is lowercase
    alphanumeric — 36 chars → log2(36) ≈ 5.17 bits per char → 12 chars ≈ 62
    bits of entropy, enough for v0.1 ID uniqueness within a single database.
    """
    return f"{prefix}-" + "".join(secrets.choice(_ALPHABET) for _ in range(length))
