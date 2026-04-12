# 0.3.0-alpha.2: Chat System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time chat (LLM streaming) to ai-accounts — CRUD for conversations, SSE streaming for token delivery, backend implementations for all four providers, TypeScript client, Vue composable and styled components.

**Architecture:** ChatService orchestrates conversation lifecycle via HistoryRepository (already scaffolded in storage). Each backend implements `chat()` returning `AsyncIterator[ChatStreamEvent]`. Litestar serves SSE via `POST /api/v1/conversations/{id}/messages`. The ts-core client exposes `streamChat()` as an async iterable. The vue-headless `useConversation` composable wraps the client and exposes reactive state. ChatPanel.vue and ChatMessage.vue provide the styled UI.

**Tech Stack:** Python (msgspec, httpx, litestar SSE), TypeScript (fetch ReadableStream SSE parser), Vue 3 (composables + SFC components)

**Reference:** Agented's `SkillConversationService`, `useAiChat.ts`, `ChatStateService`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `packages/core/src/ai_accounts_core/services/chat.py` | ChatService — session CRUD + send_message orchestration |
| Modify | `packages/core/src/ai_accounts_core/domain/chat.py` | Add ChatDelta streaming event type |
| Modify | `packages/core/src/ai_accounts_core/backends/claude.py` | Implement `chat()` via Anthropic Messages API |
| Modify | `packages/core/src/ai_accounts_core/backends/codex.py` | Implement `chat()` via OpenAI Chat Completions API |
| Modify | `packages/core/src/ai_accounts_core/backends/gemini.py` | Implement `chat()` via Google Generative AI API |
| Modify | `packages/core/src/ai_accounts_core/backends/opencode.py` | Implement `chat()` via OpenRouter API |
| Modify | `packages/core/src/ai_accounts_core/testing/fakes.py` | FakeBackend.chat() with canned streaming |
| Create | `packages/litestar/src/ai_accounts_litestar/routes/conversations.py` | CRUD + SSE streaming routes |
| Modify | `packages/litestar/src/ai_accounts_litestar/app.py` | Register ConversationsController + ChatService DI |
| Create | `packages/ts-core/src/types/chat.ts` | ChatSession, ChatMessage, ChatDelta TS types |
| Create | `packages/ts-core/src/client/chat-stream.ts` | parseSseChatEvents() SSE parser |
| Modify | `packages/ts-core/src/client/index.ts` | Add conversation client methods |
| Modify | `packages/ts-core/src/index.ts` | Re-export chat types |
| Create | `packages/vue-headless/src/composables/useConversation.ts` | Reactive chat state machine |
| Modify | `packages/vue-headless/src/index.ts` | Re-export useConversation |
| Create | `packages/vue-styled/src/components/ChatPanel.vue` | Chat UI with message list + input |
| Create | `packages/vue-styled/src/components/ChatMessage.vue` | Single message bubble |
| Modify | `packages/vue-styled/src/index.ts` | Re-export ChatPanel, ChatMessage |

---

## Task 1: Chat Domain Events

**Files:**
- Modify: `packages/core/src/ai_accounts_core/domain/chat.py`
- Test: `packages/core/tests/domain/test_chat_events.py`

- [ ] **Step 1: Write failing test for ChatDelta serialization**

Create `packages/core/tests/domain/__init__.py` (empty) and:

```python
# packages/core/tests/domain/test_chat_events.py
import msgspec

from ai_accounts_core.domain.chat import ChatDelta, ChatRole


def test_token_delta_roundtrip():
    delta = ChatDelta(kind="token", text="Hello")
    raw = msgspec.json.encode(delta)
    decoded = msgspec.json.decode(raw, type=ChatDelta)
    assert decoded.kind == "token"
    assert decoded.text == "Hello"
    assert decoded.finish_reason is None


def test_done_delta_roundtrip():
    delta = ChatDelta(kind="done", finish_reason="stop")
    raw = msgspec.json.encode(delta)
    decoded = msgspec.json.decode(raw, type=ChatDelta)
    assert decoded.kind == "done"
    assert decoded.finish_reason == "stop"
    assert decoded.text is None


def test_error_delta_roundtrip():
    delta = ChatDelta(kind="error", text="rate limited")
    raw = msgspec.json.encode(delta)
    decoded = msgspec.json.decode(raw, type=ChatDelta)
    assert decoded.kind == "error"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/core && python -m pytest tests/domain/test_chat_events.py -v
```

Expected: ImportError — `ChatDelta` not defined.

- [ ] **Step 3: Add ChatDelta to domain/chat.py**

Append to `packages/core/src/ai_accounts_core/domain/chat.py`:

```python
class ChatDelta(msgspec.Struct, frozen=True, kw_only=True):
    """Single streaming event from a chat response.

    kind: "token" | "done" | "error"
    """
    kind: str
    text: str | None = None
    finish_reason: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/core && python -m pytest tests/domain/test_chat_events.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/domain/chat.py packages/core/tests/domain/
git commit -m "feat(core): add ChatDelta streaming event type"
```

---

## Task 2: ChatService — Session CRUD

**Files:**
- Create: `packages/core/src/ai_accounts_core/services/chat.py`
- Test: `packages/core/tests/services/test_chat_service.py`

- [ ] **Step 1: Write failing test for session CRUD**

```python
# packages/core/tests/services/test_chat_service.py
import pytest

from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.testing.fakes import FakeStorage, FakeVault, FakeBackend


@pytest.fixture
def chat_service(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    backends = {"fake": FakeBackend()}
    from ai_accounts_core.services.accounts import AccountService

    accounts = AccountService(
        storage=storage,
        vault=vault,
        backends=backends,
        isolation_base_dir=tmp_path,
    )
    return ChatService(account_service=accounts, storage=storage)


@pytest.mark.asyncio
async def test_create_session(chat_service):
    # Create a backend first
    svc = chat_service
    backend = await svc._account_service.create(kind="fake", display_name="Test")
    session = await svc.create_session(backend_id=backend.id, model="fake-1")
    assert session.backend_id == backend.id
    assert session.model == "fake-1"
    assert session.id.startswith("cht-")


@pytest.mark.asyncio
async def test_list_sessions(chat_service):
    svc = chat_service
    backend = await svc._account_service.create(kind="fake", display_name="Test")
    await svc.create_session(backend_id=backend.id, model="fake-1")
    await svc.create_session(backend_id=backend.id, model="fake-1")
    sessions = await svc.list_sessions(backend_id=backend.id)
    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_get_session(chat_service):
    svc = chat_service
    backend = await svc._account_service.create(kind="fake", display_name="Test")
    session = await svc.create_session(backend_id=backend.id, model="fake-1")
    got = await svc.get_session(session.id)
    assert got.id == session.id


@pytest.mark.asyncio
async def test_get_session_not_found(chat_service):
    with pytest.raises(KeyError):
        await chat_service.get_session("cht-nonexistent")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/core && python -m pytest tests/services/test_chat_service.py -v
```

Expected: ImportError — `ChatService` not defined.

- [ ] **Step 3: Implement ChatService**

```python
# packages/core/src/ai_accounts_core/services/chat.py
from __future__ import annotations

from datetime import UTC, datetime

from ai_accounts_core.domain.chat import ChatMessage, ChatRole, ChatSession
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.storage import StorageProtocol
from ai_accounts_core.services.accounts import AccountService


def _now() -> datetime:
    return datetime.now(UTC)


class ChatService:
    def __init__(
        self,
        *,
        account_service: AccountService,
        storage: StorageProtocol,
    ) -> None:
        self._account_service = account_service
        self._storage = storage

    async def create_session(
        self,
        *,
        backend_id: str,
        model: str,
        title: str | None = None,
    ) -> ChatSession:
        # Verify backend exists
        await self._account_service.get(backend_id)
        session = ChatSession(
            id=new_id("cht"),
            backend_id=backend_id,
            title=title,
            created_at=_now(),
            model=model,
        )
        history = await self._storage.history()
        await history.create_session(session)
        return session

    async def get_session(self, session_id: str) -> ChatSession:
        history = await self._storage.history()
        sessions = await history.list_sessions()
        for s in sessions:
            if s.id == session_id:
                return s
        raise KeyError(f"chat session not found: {session_id}")

    async def list_sessions(
        self, *, backend_id: str | None = None
    ) -> list[ChatSession]:
        history = await self._storage.history()
        return await history.list_sessions(backend_id=backend_id)

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        # Verify session exists
        await self.get_session(session_id)
        history = await self._storage.history()
        return await history.list_messages(session_id)

    async def append_message(self, message: ChatMessage) -> None:
        history = await self._storage.history()
        await history.append_message(message)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/core && python -m pytest tests/services/test_chat_service.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/services/chat.py packages/core/tests/services/test_chat_service.py
git commit -m "feat(core): ChatService — session CRUD + message history"
```

---

## Task 3: ChatService.send_message — Streaming Orchestration

**Files:**
- Modify: `packages/core/src/ai_accounts_core/services/chat.py`
- Test: `packages/core/tests/services/test_chat_send_message.py`

- [ ] **Step 1: Write failing test for send_message**

```python
# packages/core/tests/services/test_chat_send_message.py
import pytest

from ai_accounts_core.domain.chat import ChatDelta, ChatRole
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.testing.fakes import FakeStorage, FakeVault, FakeBackend
from ai_accounts_core.services.accounts import AccountService


@pytest.fixture
async def ready_chat(tmp_path):
    """Create a ChatService with a READY backend that has a credential."""
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage, vault=vault, backends={"fake": fake},
        isolation_base_dir=tmp_path,
    )
    backend = await accounts.create(kind="fake", display_name="Test")
    await accounts.store_credential(backend.id, b"sk-fake-test")
    await accounts.validate(backend.id)
    chat_svc = ChatService(account_service=accounts, storage=storage)
    session = await chat_svc.create_session(backend_id=backend.id, model="fake-1")
    return chat_svc, session


@pytest.mark.asyncio
async def test_send_message_streams_tokens(ready_chat):
    svc, session = await ready_chat
    deltas: list[ChatDelta] = []
    async for delta in svc.send_message(
        session_id=session.id, content="Hello"
    ):
        deltas.append(delta)
    # Should have at least one token delta and one done delta
    kinds = [d.kind for d in deltas]
    assert "token" in kinds
    assert "done" in kinds


@pytest.mark.asyncio
async def test_send_message_persists_messages(ready_chat):
    svc, session = await ready_chat
    async for _ in svc.send_message(session_id=session.id, content="Hello"):
        pass
    messages = await svc.get_messages(session.id)
    # Should have user message + assistant message
    assert len(messages) >= 2
    assert messages[0].role.value == "user"
    assert messages[1].role.value == "assistant"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/core && python -m pytest tests/services/test_chat_send_message.py -v
```

Expected: AttributeError — `send_message` not defined on ChatService.

- [ ] **Step 3: Add send_message to ChatService**

Append to `packages/core/src/ai_accounts_core/services/chat.py`:

```python
    async def send_message(
        self,
        *,
        session_id: str,
        content: str,
        role: ChatRole = ChatRole.USER,
    ) -> AsyncIterator[ChatDelta]:
        """Send a message and stream the assistant response.

        Yields ChatDelta events (token, done, error). Persists both the user
        message and the accumulated assistant response to history.
        """
        from collections.abc import AsyncIterator

        from ai_accounts_core.domain.chat import ChatDelta
        from ai_accounts_core.protocols.backend import ChatRequest

        session = await self.get_session(session_id)
        backend = await self._account_service.get(session.backend_id)
        impl = self._account_service._impl_for(backend.kind)

        # Persist user message
        user_msg = ChatMessage(
            id=new_id("msg"),
            session_id=session_id,
            role=role,
            content=content,
            created_at=_now(),
        )
        await self.append_message(user_msg)

        # Build context from history
        history_msgs = await self.get_messages(session_id)
        chat_messages = tuple(history_msgs)

        # Get credential
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend.id)
        if stored is None:
            from ai_accounts_core.services.errors import CredentialMissing
            raise CredentialMissing(backend.id)
        plaintext = await self._account_service._vault.decrypt(
            stored.ciphertext, context={"backend_id": backend.id}
        )

        request = ChatRequest(
            messages=chat_messages,
            model=session.model or "default",
        )
        isolation_dir = self._account_service._isolation_dir(backend.id)

        # Stream response
        accumulated_text = ""
        tokens_in = None
        tokens_out = None
        model_used = None
        async for event in impl.chat(request, plaintext, isolation_dir=isolation_dir):
            delta = ChatDelta(
                kind=event.kind,
                text=event.payload if isinstance(event.payload, str) else None,
                finish_reason=event.payload if event.kind == "done" and isinstance(event.payload, str) else None,
                tokens_in=event.payload.get("tokens_in") if isinstance(event.payload, dict) else None,
                tokens_out=event.payload.get("tokens_out") if isinstance(event.payload, dict) else None,
                model=event.payload.get("model") if isinstance(event.payload, dict) else None,
            )
            if delta.kind == "token" and delta.text:
                accumulated_text += delta.text
            if delta.tokens_in is not None:
                tokens_in = delta.tokens_in
            if delta.tokens_out is not None:
                tokens_out = delta.tokens_out
            if delta.model:
                model_used = delta.model
            yield delta

        # Persist assistant response
        if accumulated_text:
            assistant_msg = ChatMessage(
                id=new_id("msg"),
                session_id=session_id,
                role=ChatRole.ASSISTANT,
                content=accumulated_text,
                created_at=_now(),
                model=model_used or session.model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            await self.append_message(assistant_msg)
```

Also add the import at the top of the file:

```python
from collections.abc import AsyncIterator
from ai_accounts_core.domain.chat import ChatDelta, ChatMessage, ChatRole, ChatSession
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent
```

- [ ] **Step 4: Update FakeBackend.chat() to return canned stream**

In `packages/core/src/ai_accounts_core/testing/fakes.py`, replace the `chat()` method:

```python
    async def chat(  # type: ignore[override]
        self,
        request: Any,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[Any]:
        from ai_accounts_core.protocols.backend import ChatStreamEvent

        self.calls.append(("chat", request))
        yield ChatStreamEvent(kind="token", payload="Hello ")
        yield ChatStreamEvent(kind="token", payload="world!")
        yield ChatStreamEvent(kind="done", payload={"tokens_in": 10, "tokens_out": 2, "model": "fake-1"})
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd packages/core && python -m pytest tests/services/test_chat_send_message.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/ai_accounts_core/services/chat.py packages/core/tests/services/test_chat_send_message.py packages/core/src/ai_accounts_core/testing/fakes.py
git commit -m "feat(core): ChatService.send_message — streaming orchestration with history"
```

---

## Task 4: Claude Backend chat() Implementation

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/claude.py`
- Test: `packages/core/tests/backends/test_claude_chat.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/backends/test_claude_chat.py
import json
import pytest
import httpx

from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent
from datetime import datetime, UTC


def _msg(role: str, content: str) -> ChatMessage:
    return ChatMessage(
        id="msg-1", session_id="s-1", role=ChatRole(role),
        content=content, created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_claude_chat_streams_tokens(tmp_path, httpx_mock):
    """Claude chat() should yield token + done events from the Anthropic API."""
    # Mock the Anthropic streaming response (SSE format)
    sse_body = (
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}\n\n'
        'event: message_delta\n'
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}\n\n'
        'event: message_stop\n'
        'data: {"type":"message_stop"}\n\n'
    )
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        content=sse_body.encode(),
        headers={"content-type": "text/event-stream"},
    )

    backend = ClaudeBackend()
    request = ChatRequest(
        messages=(_msg("user", "Hello"),),
        model="claude-sonnet-4-20250514",
    )
    events: list[ChatStreamEvent] = []
    async for event in backend.chat(request, b"sk-ant-test", isolation_dir=tmp_path):
        events.append(event)

    kinds = [e.kind for e in events]
    assert "token" in kinds
    assert "done" in kinds
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/core && python -m pytest tests/backends/test_claude_chat.py -v
```

Expected: FAIL (chat() raises NotImplementedError or doesn't exist).

- [ ] **Step 3: Implement Claude backend chat()**

Add to `packages/core/src/ai_accounts_core/backends/claude.py` — replace the existing `chat` stub. Add `httpx` import if not present:

```python
    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Stream chat via the Anthropic Messages API."""
        api_key = credential.decode("utf-8").strip()
        messages_payload = [
            {"role": m.role.value, "content": m.content}
            for m in request.messages
            if m.role != ChatRole.SYSTEM
        ]
        system_msgs = [m.content for m in request.messages if m.role == ChatRole.SYSTEM]
        body: dict[str, object] = {
            "model": request.model,
            "messages": messages_payload,
            "max_tokens": request.params.get("max_tokens", 4096),
            "stream": True,
        }
        if system_msgs:
            body["system"] = system_msgs[0]

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                json=body,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    yield ChatStreamEvent(kind="error", payload=f"API error {resp.status_code}")
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    evt_type = data.get("type", "")
                    if evt_type == "content_block_delta":
                        text = data.get("delta", {}).get("text", "")
                        if text:
                            yield ChatStreamEvent(kind="token", payload=text)
                    elif evt_type == "message_delta":
                        usage = data.get("usage", {})
                        yield ChatStreamEvent(kind="done", payload={
                            "finish_reason": data.get("delta", {}).get("stop_reason", "stop"),
                            "tokens_out": usage.get("output_tokens"),
                            "model": request.model,
                        })
```

Add required imports at top of file:

```python
import json
from collections.abc import AsyncIterator
from ai_accounts_core.domain.chat import ChatRole
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/core && python -m pytest tests/backends/test_claude_chat.py -v
```

Expected: PASS (with pytest-httpx mocking the API).

Note: You may need to `pip install pytest-httpx` if not present. Add to `[project.optional-dependencies] testing` in pyproject.toml if needed.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/claude.py packages/core/tests/backends/test_claude_chat.py
git commit -m "feat(core): Claude backend chat() — Anthropic Messages API streaming"
```

---

## Task 5: Codex, Gemini, OpenCode Backend chat() Implementations

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/codex.py`
- Modify: `packages/core/src/ai_accounts_core/backends/gemini.py`
- Modify: `packages/core/src/ai_accounts_core/backends/opencode.py`
- Test: `packages/core/tests/backends/test_codex_chat.py`
- Test: `packages/core/tests/backends/test_gemini_chat.py`
- Test: `packages/core/tests/backends/test_opencode_chat.py`

All three follow the same pattern as Claude. The key differences:

**Codex** uses OpenAI-compatible Chat Completions API at `https://api.openai.com/v1/chat/completions`:
- Header: `Authorization: Bearer {api_key}`
- SSE data format: `{"choices": [{"delta": {"content": "text"}, "finish_reason": null}]}`
- Done: `finish_reason: "stop"` with `usage` object

**Gemini** uses Google Generative AI streaming at `https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={api_key}`:
- Body: `{"contents": [{"role": "user", "parts": [{"text": "..."}]}]}`
- Response: JSON-per-chunk with `candidates[0].content.parts[0].text`

**OpenCode** uses OpenRouter API at `https://openrouter.ai/api/v1/chat/completions`:
- Same OpenAI-compatible format as Codex
- Header: `Authorization: Bearer {api_key}`

- [ ] **Step 1: Write failing tests for all three backends**

Create `packages/core/tests/backends/test_codex_chat.py`:

```python
import json
import pytest

from ai_accounts_core.backends.codex import CodexBackend
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent
from datetime import datetime, UTC


def _msg(role, content):
    return ChatMessage(
        id="m1", session_id="s1", role=ChatRole(role),
        content=content, created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_codex_chat_streams(tmp_path, httpx_mock):
    sse = (
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\n'
        'data: [DONE]\n\n'
    )
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        content=sse.encode(),
        headers={"content-type": "text/event-stream"},
    )
    backend = CodexBackend()
    events = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="gpt-4o"),
        b"sk-test", isolation_dir=tmp_path,
    ):
        events.append(e)
    assert any(e.kind == "token" for e in events)
    assert any(e.kind == "done" for e in events)
```

Create `packages/core/tests/backends/test_gemini_chat.py`:

```python
import json
import pytest

from ai_accounts_core.backends.gemini import GeminiBackend
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent
from datetime import datetime, UTC


def _msg(role, content):
    return ChatMessage(
        id="m1", session_id="s1", role=ChatRole(role),
        content=content, created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_gemini_chat_streams(tmp_path, httpx_mock):
    sse = (
        'data: {"candidates":[{"content":{"parts":[{"text":"Hi"}]}}]}\n\n'
        'data: {"candidates":[{"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":1}}\n\n'
    )
    httpx_mock.add_response(
        method="POST",
        content=sse.encode(),
        headers={"content-type": "text/event-stream"},
    )
    backend = GeminiBackend()
    events = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="gemini-2.0-flash"),
        b"test-key", isolation_dir=tmp_path,
    ):
        events.append(e)
    assert any(e.kind == "token" for e in events)
    assert any(e.kind == "done" for e in events)
```

Create `packages/core/tests/backends/test_opencode_chat.py`:

```python
import json
import pytest

from ai_accounts_core.backends.opencode import OpenCodeBackend
from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent
from datetime import datetime, UTC


def _msg(role, content):
    return ChatMessage(
        id="m1", session_id="s1", role=ChatRole(role),
        content=content, created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_opencode_chat_streams(tmp_path, httpx_mock):
    sse = (
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\n'
        'data: [DONE]\n\n'
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        content=sse.encode(),
        headers={"content-type": "text/event-stream"},
    )
    backend = OpenCodeBackend()
    events = []
    async for e in backend.chat(
        ChatRequest(messages=(_msg("user", "Hi"),), model="openai/gpt-4o"),
        b"sk-test", isolation_dir=tmp_path,
    ):
        events.append(e)
    assert any(e.kind == "token" for e in events)
    assert any(e.kind == "done" for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd packages/core && python -m pytest tests/backends/test_codex_chat.py tests/backends/test_gemini_chat.py tests/backends/test_opencode_chat.py -v
```

- [ ] **Step 3: Implement Codex chat()**

In `packages/core/src/ai_accounts_core/backends/codex.py`, replace the `chat` stub:

```python
    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        api_key = credential.decode("utf-8").strip()
        messages = [{"role": m.role.value, "content": m.content} for m in request.messages]
        body = {
            "model": request.model,
            "messages": messages,
            "stream": True,
        }
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", "https://api.openai.com/v1/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    yield ChatStreamEvent(kind="error", payload=f"API error {resp.status_code}")
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    data = json.loads(payload)
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    if text := delta.get("content"):
                        yield ChatStreamEvent(kind="token", payload=text)
                    if choice.get("finish_reason"):
                        usage = data.get("usage", {})
                        yield ChatStreamEvent(kind="done", payload={
                            "finish_reason": choice["finish_reason"],
                            "tokens_in": usage.get("prompt_tokens"),
                            "tokens_out": usage.get("completion_tokens"),
                            "model": request.model,
                        })
```

- [ ] **Step 4: Implement Gemini chat()**

In `packages/core/src/ai_accounts_core/backends/gemini.py`, replace the `chat` stub:

```python
    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        api_key = credential.decode("utf-8").strip()
        contents = []
        for m in request.messages:
            role = "model" if m.role == ChatRole.ASSISTANT else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{request.model}:streamGenerateContent?alt=sse&key={api_key}"
        )
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", url, json={"contents": contents}, timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    yield ChatStreamEvent(kind="error", payload=f"API error {resp.status_code}")
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    cand = candidates[0]
                    parts = cand.get("content", {}).get("parts", [])
                    for part in parts:
                        if text := part.get("text"):
                            yield ChatStreamEvent(kind="token", payload=text)
                    if cand.get("finishReason"):
                        usage = data.get("usageMetadata", {})
                        yield ChatStreamEvent(kind="done", payload={
                            "finish_reason": cand["finishReason"],
                            "tokens_in": usage.get("promptTokenCount"),
                            "tokens_out": usage.get("candidatesTokenCount"),
                            "model": request.model,
                        })
```

- [ ] **Step 5: Implement OpenCode chat()**

In `packages/core/src/ai_accounts_core/backends/opencode.py`, replace the `chat` stub (same as Codex but different URL):

```python
    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        api_key = credential.decode("utf-8").strip()
        messages = [{"role": m.role.value, "content": m.content} for m in request.messages]
        body = {"model": request.model, "messages": messages, "stream": True}
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", "https://openrouter.ai/api/v1/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    yield ChatStreamEvent(kind="error", payload=f"API error {resp.status_code}")
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    data = json.loads(payload)
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    if text := delta.get("content"):
                        yield ChatStreamEvent(kind="token", payload=text)
                    if choice.get("finish_reason"):
                        usage = data.get("usage", {})
                        yield ChatStreamEvent(kind="done", payload={
                            "finish_reason": choice["finish_reason"],
                            "tokens_in": usage.get("prompt_tokens"),
                            "tokens_out": usage.get("completion_tokens"),
                            "model": request.model,
                        })
```

- [ ] **Step 6: Run all backend chat tests**

```bash
cd packages/core && python -m pytest tests/backends/test_claude_chat.py tests/backends/test_codex_chat.py tests/backends/test_gemini_chat.py tests/backends/test_opencode_chat.py -v
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/ packages/core/tests/backends/
git commit -m "feat(core): chat() implementations for all four backends (Claude, Codex, Gemini, OpenCode)"
```

---

## Task 6: Litestar Conversation Routes

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/conversations.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Test: `packages/litestar/tests/test_conversation_routes.py`

- [ ] **Step 1: Write failing test**

```python
# packages/litestar/tests/test_conversation_routes.py
import pytest
from litestar.testing import AsyncTestClient

from ai_accounts_core.testing.fakes import FakeBackend, FakeStorage, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest.fixture
async def client(tmp_path):
    config = AiAccountsConfig(
        storage=FakeStorage(),
        vault=FakeVault(),
        backends=(FakeBackend(),),
        backend_dirs_path=tmp_path,
    )
    app = create_app(config)
    async with AsyncTestClient(app) as tc:
        yield tc


@pytest.mark.asyncio
async def test_create_and_list_sessions(client):
    # Create a backend first
    r = await client.post("/api/v1/backends/", json={
        "kind": "fake", "display_name": "T", "config": {}
    })
    assert r.status_code == 201
    backend_id = r.json()["id"]

    # Create a chat session
    r = await client.post("/api/v1/conversations/", json={
        "backend_id": backend_id, "model": "fake-1"
    })
    assert r.status_code == 201
    session = r.json()
    assert session["backend_id"] == backend_id
    assert session["model"] == "fake-1"

    # List sessions
    r = await client.get(f"/api/v1/conversations/?backend_id={backend_id}")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


@pytest.mark.asyncio
async def test_get_session(client):
    r = await client.post("/api/v1/backends/", json={
        "kind": "fake", "display_name": "T", "config": {}
    })
    backend_id = r.json()["id"]
    r = await client.post("/api/v1/conversations/", json={
        "backend_id": backend_id, "model": "fake-1"
    })
    session_id = r.json()["id"]
    r = await client.get(f"/api/v1/conversations/{session_id}")
    assert r.status_code == 200
    assert r.json()["id"] == session_id


@pytest.mark.asyncio
async def test_send_message_sse(client):
    """POST /conversations/{id}/messages returns SSE stream."""
    # Setup: backend with credential
    r = await client.post("/api/v1/backends/", json={
        "kind": "fake", "display_name": "T", "config": {}
    })
    backend_id = r.json()["id"]
    await client.post(f"/api/v1/backends/{backend_id}/login", json={
        "flow_kind": "api_key", "inputs": {"key": "sk-fake-test"}
    })
    await client.post(f"/api/v1/backends/{backend_id}/validate")

    r = await client.post("/api/v1/conversations/", json={
        "backend_id": backend_id, "model": "fake-1"
    })
    session_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/conversations/{session_id}/messages",
        json={"content": "Hello"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/litestar && python -m pytest tests/test_conversation_routes.py -v
```

Expected: ImportError or 404 — routes don't exist yet.

- [ ] **Step 3: Create conversations controller**

```python
# packages/litestar/src/ai_accounts_litestar/routes/conversations.py
from __future__ import annotations

import msgspec
from litestar import Controller, get, post
from litestar.response import Stream

from ai_accounts_core.services.chat import ChatService


class ConversationsController(Controller):
    path = "/api/v1/conversations"

    @post("/", status_code=201)
    async def create_session(
        self,
        chat_service: ChatService,
        data: dict,
    ) -> dict:
        session = await chat_service.create_session(
            backend_id=data["backend_id"],
            model=data["model"],
            title=data.get("title"),
        )
        return {
            "id": session.id,
            "backend_id": session.backend_id,
            "model": session.model,
            "title": session.title,
            "created_at": session.created_at.isoformat(),
        }

    @get("/")
    async def list_sessions(
        self,
        chat_service: ChatService,
        backend_id: str | None = None,
    ) -> dict:
        sessions = await chat_service.list_sessions(backend_id=backend_id)
        return {
            "items": [
                {
                    "id": s.id,
                    "backend_id": s.backend_id,
                    "model": s.model,
                    "title": s.title,
                    "created_at": s.created_at.isoformat(),
                }
                for s in sessions
            ]
        }

    @get("/{session_id:str}")
    async def get_session(
        self,
        chat_service: ChatService,
        session_id: str,
    ) -> dict:
        session = await chat_service.get_session(session_id)
        messages = await chat_service.get_messages(session_id)
        return {
            "id": session.id,
            "backend_id": session.backend_id,
            "model": session.model,
            "title": session.title,
            "created_at": session.created_at.isoformat(),
            "messages": [
                {
                    "id": m.id,
                    "role": m.role.value,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                    "model": m.model,
                    "tokens_in": m.tokens_in,
                    "tokens_out": m.tokens_out,
                }
                for m in messages
            ],
        }

    @post("/{session_id:str}/messages")
    async def send_message(
        self,
        chat_service: ChatService,
        session_id: str,
        data: dict,
    ) -> Stream:
        async def generate():
            async for delta in chat_service.send_message(
                session_id=session_id,
                content=data["content"],
            ):
                payload = msgspec.json.encode(delta).decode()
                yield f"event: chat\ndata: {payload}\n\n"

        return Stream(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
```

- [ ] **Step 4: Wire ConversationsController and ChatService into app.py**

In `packages/litestar/src/ai_accounts_litestar/app.py`:

Add import:
```python
from ai_accounts_core.services.chat import ChatService
from .routes.conversations import ConversationsController
```

After `onboarding_service = ...`, add:
```python
    chat_service = ChatService(
        account_service=account_service,
        storage=config.storage,
    )
```

Add provider:
```python
    def _provide_chat_service() -> ChatService:
        return chat_service
```

Add to dependencies dict:
```python
        "chat_service": Provide(_provide_chat_service, sync_to_thread=False),
```

Add `ConversationsController` to `route_handlers` list.

- [ ] **Step 5: Run test to verify it passes**

```bash
cd packages/litestar && python -m pytest tests/test_conversation_routes.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add packages/litestar/src/ai_accounts_litestar/routes/conversations.py packages/litestar/src/ai_accounts_litestar/app.py packages/litestar/tests/test_conversation_routes.py
git commit -m "feat(litestar): conversation routes — CRUD + SSE streaming"
```

---

## Task 7: TypeScript Chat Types and SSE Parser

**Files:**
- Create: `packages/ts-core/src/types/chat.ts`
- Create: `packages/ts-core/src/client/chat-stream.ts`
- Modify: `packages/ts-core/src/client/index.ts`
- Modify: `packages/ts-core/src/index.ts`
- Test: `packages/ts-core/tests/chat.test.ts`

- [ ] **Step 1: Create chat types**

```typescript
// packages/ts-core/src/types/chat.ts

export interface ChatSessionDTO {
  id: string;
  backend_id: string;
  model: string | null;
  title: string | null;
  created_at: string;
}

export interface ChatMessageDTO {
  id: string;
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  created_at: string;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
}

export interface ChatSessionDetailDTO extends ChatSessionDTO {
  messages: ChatMessageDTO[];
}

export interface ChatDelta {
  kind: 'token' | 'done' | 'error';
  text: string | null;
  finish_reason: string | null;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
}
```

- [ ] **Step 2: Create SSE parser**

```typescript
// packages/ts-core/src/client/chat-stream.ts

import type { ChatDelta } from '../types/chat';

export async function* parseSseChatEvents(
  response: Response
): AsyncGenerator<ChatDelta> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() ?? '';

    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (line.startsWith('data: ')) {
          const payload = line.slice(6).trim();
          if (!payload) continue;
          try {
            yield JSON.parse(payload) as ChatDelta;
          } catch {
            // skip malformed frames
          }
        }
      }
    }
  }
}
```

- [ ] **Step 3: Add conversation methods to AiAccountsClient**

Append to `packages/ts-core/src/client/index.ts`:

```typescript
  // --- Conversations ---

  async createConversation(input: {
    backend_id: string;
    model: string;
    title?: string;
  }): Promise<ChatSessionDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/conversations/`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(input),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as ChatSessionDTO;
  }

  async listConversations(backendId?: string): Promise<{ items: ChatSessionDTO[] }> {
    const qs = backendId ? `?backend_id=${encodeURIComponent(backendId)}` : '';
    const r = await this._fetch(`${this.baseUrl}/api/v1/conversations/${qs}`, {
      headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { items: ChatSessionDTO[] };
  }

  async getConversation(id: string): Promise<ChatSessionDetailDTO> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/conversations/${encodeURIComponent(id)}`,
      { headers: this.headers() },
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as ChatSessionDetailDTO;
  }

  async *streamChat(sessionId: string, content: string): AsyncIterable<ChatDelta> {
    const url = `${this.baseUrl}/api/v1/conversations/${encodeURIComponent(sessionId)}/messages`;
    const headers: Record<string, string> = {
      ...this.headers(),
      Accept: 'text/event-stream',
    };
    const r = await this._fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({ content }),
    });
    if (!r.ok) throw await toError(r);
    yield* parseSseChatEvents(r);
  }
```

Add imports at top of `index.ts`:
```typescript
import { parseSseChatEvents } from './chat-stream';
import type { ChatSessionDTO, ChatSessionDetailDTO, ChatDelta } from '../types/chat';
```

- [ ] **Step 4: Update ts-core index.ts exports**

Add to `packages/ts-core/src/index.ts`:
```typescript
export type {
  ChatSessionDTO,
  ChatSessionDetailDTO,
  ChatMessageDTO,
  ChatDelta,
} from './types/chat';
```

- [ ] **Step 5: Write tests**

```typescript
// packages/ts-core/tests/chat.test.ts
import { describe, it, expect } from 'vitest';
import type { ChatDelta, ChatSessionDTO } from '../src/types/chat';

describe('ChatDelta types', () => {
  it('token delta has expected shape', () => {
    const delta: ChatDelta = {
      kind: 'token',
      text: 'Hello',
      finish_reason: null,
      model: null,
      tokens_in: null,
      tokens_out: null,
    };
    expect(delta.kind).toBe('token');
    expect(delta.text).toBe('Hello');
  });

  it('done delta has usage info', () => {
    const delta: ChatDelta = {
      kind: 'done',
      text: null,
      finish_reason: 'stop',
      model: 'claude-sonnet-4-20250514',
      tokens_in: 50,
      tokens_out: 10,
    };
    expect(delta.finish_reason).toBe('stop');
    expect(delta.tokens_in).toBe(50);
  });
});

describe('ChatSessionDTO', () => {
  it('has expected shape', () => {
    const session: ChatSessionDTO = {
      id: 'cht-abc',
      backend_id: 'bkd-123',
      model: 'claude-sonnet-4-20250514',
      title: null,
      created_at: '2026-04-12T00:00:00Z',
    };
    expect(session.id).toBe('cht-abc');
  });
});
```

- [ ] **Step 6: Run tests**

```bash
cd packages/ts-core && pnpm test
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add packages/ts-core/src/types/chat.ts packages/ts-core/src/client/chat-stream.ts packages/ts-core/src/client/index.ts packages/ts-core/src/index.ts packages/ts-core/tests/chat.test.ts
git commit -m "feat(ts-core): chat types, SSE parser, and conversation client methods"
```

---

## Task 8: Vue Headless useConversation Composable

**Files:**
- Create: `packages/vue-headless/src/composables/useConversation.ts`
- Modify: `packages/vue-headless/src/index.ts`
- Test: `packages/vue-headless/tests/useConversation.test.ts`

- [ ] **Step 1: Create composable**

```typescript
// packages/vue-headless/src/composables/useConversation.ts
import { ref, shallowRef, type Ref, type ShallowRef } from 'vue';
import type {
  AiAccountsClient,
  ChatSessionDTO,
  ChatMessageDTO,
  ChatDelta,
} from '@ai-accounts/ts-core';

export interface UseConversationReturn {
  sessionId: Ref<string | null>;
  messages: ShallowRef<ChatMessageDTO[]>;
  isStreaming: Ref<boolean>;
  streamingText: Ref<string>;
  error: Ref<string | null>;
  create: (backendId: string, model: string) => Promise<void>;
  send: (content: string) => Promise<void>;
  load: (id: string) => Promise<void>;
}

export function useConversation(client: AiAccountsClient): UseConversationReturn {
  const sessionId = ref<string | null>(null);
  const messages = shallowRef<ChatMessageDTO[]>([]);
  const isStreaming = ref(false);
  const streamingText = ref('');
  const error = ref<string | null>(null);

  async function create(backendId: string, model: string) {
    error.value = null;
    const session = await client.createConversation({
      backend_id: backendId,
      model,
    });
    sessionId.value = session.id;
    messages.value = [];
  }

  async function load(id: string) {
    error.value = null;
    const detail = await client.getConversation(id);
    sessionId.value = detail.id;
    messages.value = detail.messages;
  }

  async function send(content: string) {
    if (!sessionId.value) {
      error.value = 'No active session';
      return;
    }
    error.value = null;
    isStreaming.value = true;
    streamingText.value = '';

    // Optimistically add user message to list
    const userMsg: ChatMessageDTO = {
      id: `pending-${Date.now()}`,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
      model: null,
      tokens_in: null,
      tokens_out: null,
    };
    messages.value = [...messages.value, userMsg];

    try {
      let accumulated = '';
      for await (const delta of client.streamChat(sessionId.value, content)) {
        if (delta.kind === 'token' && delta.text) {
          accumulated += delta.text;
          streamingText.value = accumulated;
        } else if (delta.kind === 'error') {
          error.value = delta.text ?? 'Unknown error';
        }
      }
      // Add assistant message
      if (accumulated) {
        const assistantMsg: ChatMessageDTO = {
          id: `msg-${Date.now()}`,
          role: 'assistant',
          content: accumulated,
          created_at: new Date().toISOString(),
          model: null,
          tokens_in: null,
          tokens_out: null,
        };
        messages.value = [...messages.value, assistantMsg];
      }
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Stream failed';
    } finally {
      isStreaming.value = false;
      streamingText.value = '';
    }
  }

  return { sessionId, messages, isStreaming, streamingText, error, create, send, load };
}
```

- [ ] **Step 2: Update vue-headless index.ts exports**

Add to `packages/vue-headless/src/index.ts`:
```typescript
export { useConversation } from './composables/useConversation';
export type { UseConversationReturn } from './composables/useConversation';
```

- [ ] **Step 3: Write test**

```typescript
// packages/vue-headless/tests/useConversation.test.ts
import { describe, it, expect, vi } from 'vitest';
import { useConversation } from '../src/composables/useConversation';

function mockClient() {
  return {
    createConversation: vi.fn().mockResolvedValue({
      id: 'cht-1', backend_id: 'bkd-1', model: 'fake-1',
      title: null, created_at: '2026-04-12T00:00:00Z',
    }),
    getConversation: vi.fn().mockResolvedValue({
      id: 'cht-1', backend_id: 'bkd-1', model: 'fake-1',
      title: null, created_at: '2026-04-12T00:00:00Z',
      messages: [{ id: 'msg-1', role: 'user', content: 'Hi', created_at: '2026-04-12T00:00:00Z', model: null, tokens_in: null, tokens_out: null }],
    }),
    streamChat: vi.fn().mockImplementation(async function*() {
      yield { kind: 'token', text: 'Hello', finish_reason: null, model: null, tokens_in: null, tokens_out: null };
      yield { kind: 'done', text: null, finish_reason: 'stop', model: 'fake-1', tokens_in: 5, tokens_out: 1 };
    }),
  } as any;
}

describe('useConversation', () => {
  it('creates a session', async () => {
    const client = mockClient();
    const { create, sessionId } = useConversation(client);
    await create('bkd-1', 'fake-1');
    expect(sessionId.value).toBe('cht-1');
  });

  it('loads a session with messages', async () => {
    const client = mockClient();
    const { load, messages } = useConversation(client);
    await load('cht-1');
    expect(messages.value).toHaveLength(1);
  });

  it('sends a message and streams response', async () => {
    const client = mockClient();
    const { create, send, messages } = useConversation(client);
    await create('bkd-1', 'fake-1');
    await send('Hi');
    // Should have user + assistant messages
    expect(messages.value).toHaveLength(2);
    expect(messages.value[1].content).toBe('Hello');
  });
});
```

- [ ] **Step 4: Run tests**

```bash
cd packages/vue-headless && pnpm test
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add packages/vue-headless/src/composables/useConversation.ts packages/vue-headless/src/index.ts packages/vue-headless/tests/useConversation.test.ts
git commit -m "feat(vue-headless): useConversation composable — create, load, send with streaming"
```

---

## Task 9: Vue Styled ChatPanel and ChatMessage Components

**Files:**
- Create: `packages/vue-styled/src/components/ChatPanel.vue`
- Create: `packages/vue-styled/src/components/ChatMessage.vue`
- Modify: `packages/vue-styled/src/index.ts`
- Test: `packages/vue-styled/tests/ChatPanel.test.ts`

- [ ] **Step 1: Create ChatMessage component**

```vue
<!-- packages/vue-styled/src/components/ChatMessage.vue -->
<script setup lang="ts">
defineProps<{
  role: 'user' | 'assistant' | 'system';
  content: string;
  model?: string | null;
  tokensIn?: number | null;
  tokensOut?: number | null;
  streaming?: boolean;
}>();
</script>

<template>
  <div
    class="aia-chat-message"
    :class="[`aia-chat-message--${role}`, { 'aia-chat-message--streaming': streaming }]"
  >
    <div class="aia-chat-message__role">{{ role }}</div>
    <div class="aia-chat-message__content">{{ content }}</div>
    <div v-if="tokensIn || tokensOut" class="aia-chat-message__meta">
      <span v-if="tokensIn">{{ tokensIn }} in</span>
      <span v-if="tokensOut">{{ tokensOut }} out</span>
      <span v-if="model">{{ model }}</span>
    </div>
  </div>
</template>

<style scoped>
.aia-chat-message {
  padding: var(--aia-space-3, 12px);
  border-radius: var(--aia-radius-md, 8px);
  margin-bottom: var(--aia-space-2, 8px);
}
.aia-chat-message--user {
  background: var(--aia-color-surface-alt, #f0f0f0);
  margin-left: var(--aia-space-6, 48px);
}
.aia-chat-message--assistant {
  background: var(--aia-color-surface, #fff);
  border: 1px solid var(--aia-color-border, #e0e0e0);
  margin-right: var(--aia-space-6, 48px);
}
.aia-chat-message__role {
  font-size: var(--aia-text-xs, 11px);
  font-weight: 600;
  text-transform: uppercase;
  color: var(--aia-color-text-muted, #888);
  margin-bottom: var(--aia-space-1, 4px);
}
.aia-chat-message__content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}
.aia-chat-message__meta {
  font-size: var(--aia-text-xs, 11px);
  color: var(--aia-color-text-muted, #888);
  margin-top: var(--aia-space-1, 4px);
  display: flex;
  gap: var(--aia-space-2, 8px);
}
.aia-chat-message--streaming .aia-chat-message__content::after {
  content: '\25AE';
  animation: blink 1s step-end infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}
</style>
```

- [ ] **Step 2: Create ChatPanel component**

```vue
<!-- packages/vue-styled/src/components/ChatPanel.vue -->
<script setup lang="ts">
import { ref, nextTick, watch } from 'vue';
import ChatMessage from './ChatMessage.vue';

const props = defineProps<{
  messages: Array<{
    id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    model?: string | null;
    tokens_in?: number | null;
    tokens_out?: number | null;
  }>;
  streamingText?: string;
  isStreaming?: boolean;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  send: [content: string];
}>();

const input = ref('');
const messagesEnd = ref<HTMLElement | null>(null);

function handleSend() {
  const content = input.value.trim();
  if (!content || props.disabled || props.isStreaming) return;
  emit('send', content);
  input.value = '';
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}

watch(
  () => props.messages.length,
  () => nextTick(() => messagesEnd.value?.scrollIntoView({ behavior: 'smooth' })),
);
</script>

<template>
  <div class="aia-chat-panel">
    <div class="aia-chat-panel__messages">
      <ChatMessage
        v-for="msg in messages"
        :key="msg.id"
        :role="msg.role"
        :content="msg.content"
        :model="msg.model"
        :tokens-in="msg.tokens_in"
        :tokens-out="msg.tokens_out"
      />
      <ChatMessage
        v-if="isStreaming && streamingText"
        role="assistant"
        :content="streamingText"
        :streaming="true"
      />
      <div ref="messagesEnd" />
    </div>
    <div class="aia-chat-panel__input">
      <textarea
        v-model="input"
        class="aia-chat-panel__textarea"
        placeholder="Type a message..."
        rows="2"
        :disabled="disabled || isStreaming"
        @keydown="handleKeydown"
      />
      <button
        class="aia-chat-panel__send"
        :disabled="!input.trim() || disabled || isStreaming"
        @click="handleSend"
      >
        Send
      </button>
    </div>
  </div>
</template>

<style scoped>
.aia-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  font-family: var(--aia-font-sans, system-ui, sans-serif);
}
.aia-chat-panel__messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--aia-space-3, 12px);
}
.aia-chat-panel__input {
  display: flex;
  gap: var(--aia-space-2, 8px);
  padding: var(--aia-space-3, 12px);
  border-top: 1px solid var(--aia-color-border, #e0e0e0);
}
.aia-chat-panel__textarea {
  flex: 1;
  resize: none;
  padding: var(--aia-space-2, 8px);
  border: 1px solid var(--aia-color-border, #e0e0e0);
  border-radius: var(--aia-radius-md, 8px);
  font-family: inherit;
  font-size: var(--aia-text-sm, 14px);
}
.aia-chat-panel__send {
  padding: var(--aia-space-2, 8px) var(--aia-space-4, 16px);
  background: var(--aia-color-primary, #2563eb);
  color: white;
  border: none;
  border-radius: var(--aia-radius-md, 8px);
  cursor: pointer;
  font-weight: 500;
}
.aia-chat-panel__send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
```

- [ ] **Step 3: Update vue-styled index.ts exports**

Add to `packages/vue-styled/src/index.ts`:
```typescript
export { default as ChatPanel } from './components/ChatPanel.vue';
export { default as ChatMessage } from './components/ChatMessage.vue';
```

- [ ] **Step 4: Write test**

```typescript
// packages/vue-styled/tests/ChatPanel.test.ts
import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import ChatPanel from '../src/components/ChatPanel.vue';

describe('ChatPanel', () => {
  const messages = [
    { id: 'm1', role: 'user' as const, content: 'Hello', model: null, tokens_in: null, tokens_out: null },
    { id: 'm2', role: 'assistant' as const, content: 'Hi there!', model: 'fake-1', tokens_in: 5, tokens_out: 3 },
  ];

  it('renders messages', () => {
    const wrapper = mount(ChatPanel, { props: { messages } });
    expect(wrapper.text()).toContain('Hello');
    expect(wrapper.text()).toContain('Hi there!');
  });

  it('emits send on button click', async () => {
    const wrapper = mount(ChatPanel, { props: { messages } });
    const textarea = wrapper.find('textarea');
    await textarea.setValue('New message');
    await wrapper.find('button').trigger('click');
    expect(wrapper.emitted('send')?.[0]).toEqual(['New message']);
  });

  it('shows streaming text', () => {
    const wrapper = mount(ChatPanel, {
      props: { messages, isStreaming: true, streamingText: 'Generating...' },
    });
    expect(wrapper.text()).toContain('Generating...');
  });

  it('disables input while streaming', () => {
    const wrapper = mount(ChatPanel, {
      props: { messages, isStreaming: true },
    });
    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined();
  });
});
```

- [ ] **Step 5: Run tests**

```bash
cd packages/vue-styled && pnpm test
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add packages/vue-styled/src/components/ChatPanel.vue packages/vue-styled/src/components/ChatMessage.vue packages/vue-styled/src/index.ts packages/vue-styled/tests/ChatPanel.test.ts
git commit -m "feat(vue-styled): ChatPanel + ChatMessage components with streaming indicator"
```

---

## Task 10: Version Bump + Release

**Files:**
- Modify: `packages/core/pyproject.toml` (version → 0.3.0a3)
- Modify: `packages/litestar/pyproject.toml` (version → 0.3.0a3)
- Modify: `packages/ts-core/package.json` (version → 0.3.0-alpha.3)
- Modify: `packages/vue-headless/package.json` (version → 0.3.0-alpha.3)
- Modify: `packages/vue-styled/package.json` (version → 0.3.0-alpha.3)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump all versions**

Update version strings in all package manifests to their alpha.3 values.

- [ ] **Step 2: Update CHANGELOG.md**

Add alpha.2 section:
```markdown
## 0.3.0-alpha.3 (Chat) — 2026-04-XX

### Added
- `ChatService` — session CRUD + streaming message orchestration
- Backend `chat()` for Claude (Anthropic API), Codex (OpenAI API), Gemini (Google AI), OpenCode (OpenRouter)
- Litestar routes: `POST /api/v1/conversations/`, `GET /api/v1/conversations/`, `GET /api/v1/conversations/{id}`, `POST /api/v1/conversations/{id}/messages` (SSE)
- `@ai-accounts/ts-core`: `createConversation()`, `listConversations()`, `getConversation()`, `streamChat()` client methods
- `@ai-accounts/vue-headless`: `useConversation` composable
- `@ai-accounts/vue-styled`: `ChatPanel`, `ChatMessage` components
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "release: 0.3.0-alpha.3 (chat system)"
```
