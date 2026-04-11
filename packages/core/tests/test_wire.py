import msgspec

from ai_accounts_core.protocol.wire import (
    ChatDoneEvent,
    ChatTokenEvent,
    ErrorEvent,
    PtyOutputEvent,
    SessionStartEvent,
    decode_wire_event,
    encode_wire_event,
)

WIRE_PROTOCOL_VERSION = 1


def test_chat_token_event_roundtrip():
    event = ChatTokenEvent(
        protocol_version=WIRE_PROTOCOL_VERSION,
        session_id="sess-1",
        token="hello",
        model="claude-sonnet-4-5",
    )
    encoded = encode_wire_event(event)
    decoded = decode_wire_event(encoded)
    assert decoded == event


def test_chat_done_event_roundtrip():
    event = ChatDoneEvent(
        protocol_version=WIRE_PROTOCOL_VERSION,
        session_id="sess-1",
        tokens_in=12,
        tokens_out=34,
    )
    assert decode_wire_event(encode_wire_event(event)) == event


def test_pty_output_event_roundtrip():
    event = PtyOutputEvent(
        protocol_version=WIRE_PROTOCOL_VERSION,
        session_id="sess-pty",
        data=b"\x1b[32mhi\x1b[0m",
    )
    assert decode_wire_event(encode_wire_event(event)) == event


def test_error_event_roundtrip():
    event = ErrorEvent(
        protocol_version=WIRE_PROTOCOL_VERSION,
        code="backend_unavailable",
        message="claude CLI not found",
    )
    assert decode_wire_event(encode_wire_event(event)) == event


def test_tagged_union_discrimination():
    start = SessionStartEvent(
        protocol_version=WIRE_PROTOCOL_VERSION,
        session_id="s1",
        kind="chat",
        backend_id="bkd-1",
    )
    raw = encode_wire_event(start)
    parsed = msgspec.json.decode(raw)
    assert parsed["type"] == "session_start"
