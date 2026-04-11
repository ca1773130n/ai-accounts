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
