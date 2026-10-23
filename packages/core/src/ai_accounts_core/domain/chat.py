from datetime import datetime
from enum import StrEnum

import msgspec


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(msgspec.Struct, frozen=True, kw_only=True):
    """One function call an assistant message made (OpenAI ``tool_calls[i]``)."""

    id: str
    name: str
    arguments: str = "{}"  # the raw JSON string, as providers stream it


class ChatMessage(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    session_id: str
    role: ChatRole
    content: str
    created_at: datetime
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    # Structured tool turns (0.6.3). Only transports that declare
    # `structured_tool_messages` send them (`_cliproxy_chat.openai_message`);
    # every other transport, the storage adapters and the HTTP routes read
    # role and content only, as before.
    tool_call_id: str | None = None  # role TOOL: the call this message answers
    tool_calls: tuple[ToolCall, ...] = ()  # role ASSISTANT: the calls it made
    name: str | None = None  # role TOOL: the tool's name


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

    For kind="token" and kind="error", `payload` carries the text. Matches the
    SmartChatEvent shape consumed by `@ai-accounts/vue-headless useSmartChat`.
    """

    kind: str
    payload: str | None = None
    finish_reason: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tool_id: str | None = None
    tool_name: str | None = None
    tool_arguments: str | None = None
