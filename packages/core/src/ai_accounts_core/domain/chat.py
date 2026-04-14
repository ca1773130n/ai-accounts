from datetime import datetime
from enum import Enum

import msgspec


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    session_id: str
    role: ChatRole
    content: str
    created_at: datetime
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


class ChatSession(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    backend_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime | None = None
    model: str | None = None


class ChatDelta(msgspec.Struct, frozen=True, kw_only=True):
    """Single streaming event from a chat response.
    kind: "token" | "tool_call" | "done" | "error"
    """
    kind: str
    text: str | None = None
    finish_reason: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tool_id: str | None = None
    tool_name: str | None = None
    tool_arguments: str | None = None
