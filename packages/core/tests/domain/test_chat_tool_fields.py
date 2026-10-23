"""ChatMessage's structured tool fields (0.6.3): tool_call_id, tool_calls, name.

They are additive. A message built, encoded or stored the 0.6.2 way must come
out exactly as before, and the storage adapters keep persisting role and
content only (the fields ride a single request, never history). The storage
conformance suite itself runs unchanged in tests/storage/test_sqlite_storage.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import msgspec
import pytest
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.domain.backend import Backend, BackendKind, BackendStatus
from ai_accounts_core.domain.chat import ChatMessage, ChatRole, ChatSession, ToolCall

_AT = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def test_defaults_leave_a_plain_message_unchanged() -> None:
    msg = ChatMessage(id="m", session_id="s", role=ChatRole.USER, content="hi", created_at=_AT)
    assert msg.tool_call_id is None
    assert msg.tool_calls == ()
    assert msg.name is None


def test_msgspec_round_trip_keeps_the_tool_fields() -> None:
    assistant = ChatMessage(
        id="a",
        session_id="s",
        role=ChatRole.ASSISTANT,
        content="",
        created_at=_AT,
        tool_calls=(ToolCall(id="call_0", name="search", arguments='{"query": "x"}'),),
    )
    tool = ChatMessage(
        id="t",
        session_id="s",
        role=ChatRole.TOOL,
        content='{"results": []}',
        created_at=_AT,
        tool_call_id="call_0",
        name="search",
    )
    for msg in (assistant, tool):
        assert msgspec.json.decode(msgspec.json.encode(msg), type=ChatMessage) == msg


def test_tool_call_arguments_default_to_an_empty_object() -> None:
    assert ToolCall(id="c", name="search").arguments == "{}"


def test_json_written_before_0_6_3_decodes_with_defaults() -> None:
    old = (
        b'{"id":"m","session_id":"s","role":"user","content":"hi",'
        b'"created_at":"2026-10-23T12:00:00Z","model":null,"tokens_in":null,"tokens_out":null}'
    )
    msg = msgspec.json.decode(old, type=ChatMessage)
    assert (msg.role, msg.content) == (ChatRole.USER, "hi")
    assert (msg.tool_call_id, msg.tool_calls, msg.name) == (None, (), None)


@pytest.mark.asyncio
async def test_sqlite_stores_role_and_content_only(tmp_path: Path) -> None:
    """The fields are per-request structure. History keeps what it kept in
    0.6.2, so a stored tool message reads back without them."""
    storage = SqliteStorage(str(tmp_path / "test.db"))
    try:
        await storage.migrate()
        await (await storage.backends()).create(
            Backend(
                id="b",
                kind=BackendKind.CODEX,
                display_name="Codex",
                config={},
                status=BackendStatus.READY,
                created_at=_AT,
            )
        )
        history = await storage.history()
        await history.create_session(
            ChatSession(id="s", backend_id="b", title=None, created_at=_AT)
        )
        await history.append_message(
            ChatMessage(
                id="t",
                session_id="s",
                role=ChatRole.TOOL,
                content="result",
                created_at=_AT,
                tool_call_id="call_0",
                name="search",
            )
        )
        (stored,) = await history.list_messages("s")
    finally:
        await storage.close()
    assert (stored.role, stored.content) == (ChatRole.TOOL, "result")
    assert (stored.tool_call_id, stored.tool_calls, stored.name) == (None, (), None)
