from pathlib import Path
from typing import Any, Literal

import msgspec


class AiAccountsConfig(msgspec.Struct, kw_only=True):
    env: Literal["development", "production"] = "development"
    storage: Any = None
    vault: Any = None
    auth: Any = None
    backends: tuple[Any, ...] = ()
    cors_origins: tuple[str, ...] = ()
    backend_dirs_path: Path = Path("./backend_dirs")
    login_session_ttl_seconds: float = 600.0
    # Opt-in keep-alive: every N seconds, send a 1-token probe chat through
    # each READY (and ERROR — keep_alive doubles as recovery) account so idle
    # OAuth tokens stay fresh. None = disabled. Each tick spends real tokens
    # (cheapest model per kind, e.g. Haiku for Claude) — enable deliberately.
    keep_alive_interval_seconds: float | None = None
