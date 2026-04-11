import msgspec


class Principal(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    display_name: str
    scopes: frozenset[str] = frozenset()
