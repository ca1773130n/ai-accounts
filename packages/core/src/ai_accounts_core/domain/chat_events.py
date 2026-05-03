import msgspec


class AllModeEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str  # "backend_delta" | "backend_complete" | "backend_error" | "backend_timeout"
    backend: str  # backend_id (bkd-…) — keeps streams unique per account
    backend_kind: str | None = None  # "claude" / "codex" / "gemini" — for color/label
    account_label: str | None = None  # display_name / email — for the card title
    text: str | None = None
    error: str | None = None


class CompoundEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str
    backend: str | None = None
    backend_kind: str | None = None
    account_label: str | None = None
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
