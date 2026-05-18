import msgspec
from ai_accounts_core.domain.chat_events import AllModeEvent, CompoundEvent, ToolCallEvent


def test_tool_call_event_encode():
    event = ToolCallEvent(
        id="tc_1", name="read_file", arguments='{"path": "/tmp"}', group_type="tool_call"
    )
    data = msgspec.json.encode(event)
    decoded = msgspec.json.decode(data, type=ToolCallEvent)
    assert decoded.id == "tc_1"
    assert decoded.name == "read_file"
    assert decoded.group_type == "tool_call"


def test_tool_call_event_defaults():
    event = ToolCallEvent(id="tc_2")
    assert event.name is None
    assert event.arguments is None
    assert event.group_type == "tool_call"


def test_tool_call_event_reasoning_type():
    event = ToolCallEvent(id="tc_3", group_type="reasoning")
    assert event.group_type == "reasoning"


def test_existing_events_still_work():
    ame = AllModeEvent(kind="backend_delta", backend="claude", text="hi")
    assert ame.backend == "claude"
    ce = CompoundEvent(kind="start")
    assert ce.kind == "start"
