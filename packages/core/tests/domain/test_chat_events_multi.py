import msgspec
from ai_accounts_core.domain.chat_events import AllModeEvent, CompoundEvent

# ── AllModeEvent ──


def test_all_mode_event_roundtrip():
    event = AllModeEvent(kind="backend_delta", backend="claude-1", text="Hello")
    data = msgspec.json.encode(event)
    decoded = msgspec.json.decode(data, type=AllModeEvent)
    assert decoded == event
    assert decoded.kind == "backend_delta"
    assert decoded.backend == "claude-1"
    assert decoded.text == "Hello"


def test_all_mode_event_error():
    event = AllModeEvent(kind="backend_error", backend="gpt-2", error="rate limited")
    data = msgspec.json.encode(event)
    decoded = msgspec.json.decode(data, type=AllModeEvent)
    assert decoded == event
    assert decoded.error == "rate limited"
    assert decoded.text is None


def test_all_mode_event_defaults():
    event = AllModeEvent(kind="backend_complete", backend="claude-1")
    assert event.text is None
    assert event.error is None


def test_all_mode_event_timeout():
    event = AllModeEvent(kind="backend_timeout", backend="gpt-2")
    data = msgspec.json.encode(event)
    decoded = msgspec.json.decode(data, type=AllModeEvent)
    assert decoded == event
    assert decoded.kind == "backend_timeout"


# ── CompoundEvent ──


def test_compound_event_roundtrip():
    event = CompoundEvent(
        kind="primary_selected",
        primary_backend="claude-1",
        backends_collected=("claude-1", "gpt-2"),
    )
    data = msgspec.json.encode(event)
    decoded = msgspec.json.decode(data, type=CompoundEvent)
    assert decoded == event
    assert decoded.primary_backend == "claude-1"
    assert decoded.backends_collected == ("claude-1", "gpt-2")


def test_compound_event_with_text():
    event = CompoundEvent(kind="token", backend="claude-1", text="streaming")
    data = msgspec.json.encode(event)
    decoded = msgspec.json.decode(data, type=CompoundEvent)
    assert decoded == event
    assert decoded.text == "streaming"


def test_compound_event_error():
    event = CompoundEvent(kind="error", error="all backends failed")
    data = msgspec.json.encode(event)
    decoded = msgspec.json.decode(data, type=CompoundEvent)
    assert decoded == event
    assert decoded.error == "all backends failed"


def test_compound_event_defaults():
    event = CompoundEvent(kind="done")
    assert event.backend is None
    assert event.text is None
    assert event.primary_backend is None
    assert event.backends_collected is None
    assert event.error is None
