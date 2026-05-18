"""Load ``cliproxy_compat.toml`` and expose its values to ``manager.py``.

Falls back to hard-coded defaults on any error so a broken toml never bricks
the wizard. The defaults match what was previously inline in ``manager.py``.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_TOML_PATH = Path(__file__).parent / "cliproxy_compat.toml"


_DEFAULT_DEVICE_CODE_PATTERN = r"code[:\s]+([A-Z0-9]{4}-?[A-Z0-9]{4,8})"
_DEFAULT_ALLOWED_PORTS = frozenset({1455, 8085, 54545})
_DEFAULT_ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    "/auth/callback",
    "/callback",
    "/cb",
    "/oauth",
)
_DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1"})
_DEFAULT_OWNED_BY: dict[str, str] = {
    "claude": "anthropic",
    "codex": "openai",
    "gemini": "google",
}


class _Compat:
    __slots__ = (
        "device_code_re",
        "allowed_ports",
        "allowed_path_prefixes",
        "allowed_hosts",
        "owned_by",
    )

    def __init__(
        self,
        *,
        device_code_re: re.Pattern[str],
        allowed_ports: frozenset[int],
        allowed_path_prefixes: tuple[str, ...],
        allowed_hosts: frozenset[str],
        owned_by: dict[str, str],
    ) -> None:
        self.device_code_re = device_code_re
        self.allowed_ports = allowed_ports
        self.allowed_path_prefixes = allowed_path_prefixes
        self.allowed_hosts = allowed_hosts
        self.owned_by = owned_by


def _defaults() -> _Compat:
    return _Compat(
        device_code_re=re.compile(_DEFAULT_DEVICE_CODE_PATTERN, re.IGNORECASE),
        allowed_ports=_DEFAULT_ALLOWED_PORTS,
        allowed_path_prefixes=_DEFAULT_ALLOWED_PATH_PREFIXES,
        allowed_hosts=_DEFAULT_ALLOWED_HOSTS,
        owned_by=dict(_DEFAULT_OWNED_BY),
    )


def _load() -> _Compat:
    try:
        with _TOML_PATH.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return _defaults()

    dc = data.get("device_code", {}) if isinstance(data, dict) else {}
    pattern = dc.get("pattern") if isinstance(dc, dict) else None
    flags = re.IGNORECASE if (isinstance(dc, dict) and dc.get("flags_ignorecase")) else 0
    if not isinstance(pattern, str):
        pattern = _DEFAULT_DEVICE_CODE_PATTERN
    try:
        device_code_re = re.compile(pattern, flags)
    except re.error:
        device_code_re = re.compile(_DEFAULT_DEVICE_CODE_PATTERN, re.IGNORECASE)

    cb = data.get("callback", {}) if isinstance(data, dict) else {}
    ports_raw = cb.get("allowed_ports") if isinstance(cb, dict) else None
    if isinstance(ports_raw, list) and all(isinstance(p, int) for p in ports_raw):
        allowed_ports = frozenset(ports_raw)
    else:
        allowed_ports = _DEFAULT_ALLOWED_PORTS

    paths_raw = cb.get("allowed_path_prefixes") if isinstance(cb, dict) else None
    if isinstance(paths_raw, list) and all(isinstance(p, str) for p in paths_raw):
        allowed_path_prefixes = tuple(paths_raw)
    else:
        allowed_path_prefixes = _DEFAULT_ALLOWED_PATH_PREFIXES

    hosts_raw = cb.get("allowed_hosts") if isinstance(cb, dict) else None
    if isinstance(hosts_raw, list) and all(isinstance(h, str) for h in hosts_raw):
        allowed_hosts = frozenset(hosts_raw)
    else:
        allowed_hosts = _DEFAULT_ALLOWED_HOSTS

    providers = data.get("providers", {}) if isinstance(data, dict) else {}
    if isinstance(providers, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in providers.items()
    ):
        owned_by = dict(providers)
    else:
        owned_by = dict(_DEFAULT_OWNED_BY)

    return _Compat(
        device_code_re=device_code_re,
        allowed_ports=allowed_ports,
        allowed_path_prefixes=allowed_path_prefixes,
        allowed_hosts=allowed_hosts,
        owned_by=owned_by,
    )


COMPAT = _load()
