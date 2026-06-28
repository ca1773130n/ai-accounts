from typing import Annotated, Literal

import msgspec

WIRE_PROTOCOL_VERSION = 1


class SessionStartEvent(
    msgspec.Struct, tag="session_start", tag_field="type", frozen=True, kw_only=True
):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    session_id: str
    kind: Literal["chat", "pty"]
    backend_id: str


class SessionEndEvent(
    msgspec.Struct, tag="session_end", tag_field="type", frozen=True, kw_only=True
):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    session_id: str
    reason: str | None = None


class ChatTokenEvent(msgspec.Struct, tag="chat_token", tag_field="type", frozen=True, kw_only=True):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    session_id: str
    token: str
    model: str | None = None


class ChatToolCallEvent(
    msgspec.Struct, tag="chat_tool_call", tag_field="type", frozen=True, kw_only=True
):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    session_id: str
    name: str
    arguments: str


class ChatDoneEvent(msgspec.Struct, tag="chat_done", tag_field="type", frozen=True, kw_only=True):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    session_id: str
    tokens_in: int | None = None
    tokens_out: int | None = None


class PtyOutputEvent(msgspec.Struct, tag="pty_output", tag_field="type", frozen=True, kw_only=True):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    session_id: str
    data: bytes


class PtyResizeEvent(msgspec.Struct, tag="pty_resize", tag_field="type", frozen=True, kw_only=True):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    session_id: str
    cols: int
    rows: int


class PtyExitEvent(msgspec.Struct, tag="pty_exit", tag_field="type", frozen=True, kw_only=True):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    session_id: str
    exit_code: int


class ErrorEvent(msgspec.Struct, tag="error", tag_field="type", frozen=True, kw_only=True):
    protocol_version: int = WIRE_PROTOCOL_VERSION
    code: str
    message: str
    session_id: str | None = None


WireEvent = Annotated[
    SessionStartEvent
    | SessionEndEvent
    | ChatTokenEvent
    | ChatToolCallEvent
    | ChatDoneEvent
    | PtyOutputEvent
    | PtyResizeEvent
    | PtyExitEvent
    | ErrorEvent,
    msgspec.Meta(description="Tagged union of all events flowing between server and client"),
]


_encoder = msgspec.json.Encoder()
_decoder = msgspec.json.Decoder(WireEvent)


def encode_wire_event(event: object) -> bytes:
    return _encoder.encode(event)


def decode_wire_event(raw: bytes) -> object:
    return _decoder.decode(raw)
