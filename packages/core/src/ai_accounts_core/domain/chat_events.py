import msgspec


class AllModeEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str  # "backend_delta" | "backend_complete" | "backend_error" | "backend_timeout"
    backend: str
    text: str | None = None
    error: str | None = None


class CompoundEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str
    backend: str | None = None
    text: str | None = None
    primary_backend: str | None = None
    backends_collected: tuple[str, ...] | None = None
    error: str | None = None


class ToolCallEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str = "tool_call"
    id: str = ""
    name: str | None = None
    arguments: str | None = None
    group_type: str = "tool_call"  # "tool_call" | "reasoning" | "code_execution"
