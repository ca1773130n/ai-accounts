from typing import Literal

import msgspec


class AiAccountsConfig(msgspec.Struct, frozen=True, kw_only=True):
    env: Literal["development", "production"] = "development"
    cors_origins: tuple[str, ...] = ()
