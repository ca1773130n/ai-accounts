# Smart AI Chat Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a complete `<AiChatPanel />` component with auto-scheduling, streaming markdown, multi-backend parallel/compound modes — so consumers just mount it and get a working AI chat.

**Architecture:** `ChatOrchestrator` wraps `AccountScheduler` + `ChatService` + CLIProxyAPI for single/all/compound modes. `useSmartChat` composable manages the full state machine. `AiChatPanel` renders with `density` prop controlling UI complexity. SSE streams events from `/api/v1/chat/send`.

**Tech Stack:** Python (msgspec, asyncio.TaskGroup, httpx), TypeScript, Vue 3, marked (markdown), highlight.js (code highlighting)

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `packages/core/src/ai_accounts_core/domain/chat_events.py` | AllModeEvent, CompoundEvent types |
| Create | `packages/core/src/ai_accounts_core/services/chat_orchestrator.py` | ChatOrchestrator — send_single, send_all, send_compound |
| Create | `packages/litestar/src/ai_accounts_litestar/routes/chat_send.py` | POST /api/v1/chat/send SSE route |
| Modify | `packages/litestar/src/ai_accounts_litestar/app.py` | Register ChatSendController + ChatOrchestrator DI |
| Create | `packages/ts-core/src/types/smart-chat.ts` | BackendResponse, SynthesisState, AllModeEventDTO, CompoundEventDTO |
| Create | `packages/ts-core/src/client/smart-chat-stream.ts` | parseSseSmartChatEvents() |
| Modify | `packages/ts-core/src/client/index.ts` | sendChat(), listSessions(), createSession() methods |
| Create | `packages/vue-headless/src/composables/useSmartChat.ts` | Full chat state machine |
| Create | `packages/vue-headless/src/composables/useSmartScroll.ts` | Smart scroll detection |
| Create | `packages/vue-styled/src/components/ChatBubble.vue` | Single message with markdown + copy |
| Create | `packages/vue-styled/src/components/ChatControls.vue` | Backend/account/model/mode selectors |
| Create | `packages/vue-styled/src/components/ChatInput.vue` | Textarea + send button |
| Create | `packages/vue-styled/src/components/AllModeResponses.vue` | Parallel backend response cards |
| Create | `packages/vue-styled/src/components/CompoundSynthesis.vue` | Synthesis result display |
| Rewrite | `packages/vue-styled/src/components/AiChatPanel.vue` | Main panel — orchestrates everything |
| Modify | `packages/vue-styled/package.json` | Add marked + highlight.js deps |

---

## Task 1: Chat Event Types (AllModeEvent, CompoundEvent)

**Files:**
- Create: `packages/core/src/ai_accounts_core/domain/chat_events.py`
- Test: `packages/core/tests/domain/test_chat_events_multi.py`

- [ ] **Step 1: Create event types**

```python
# packages/core/src/ai_accounts_core/domain/chat_events.py
import msgspec

class AllModeEvent(msgspec.Struct, frozen=True, kw_only=True):
    """Event from all-mode fan-out."""
    kind: str  # "backend_delta" | "backend_complete" | "backend_error" | "backend_timeout"
    backend: str
    text: str | None = None
    error: str | None = None

class CompoundEvent(msgspec.Struct, frozen=True, kw_only=True):
    """Event from compound mode (all-mode + synthesis)."""
    kind: str  # AllModeEvent kinds + "synthesis_start" | "synthesis_delta" | "synthesis_complete" | "synthesis_error"
    backend: str | None = None
    text: str | None = None
    primary_backend: str | None = None
    backends_collected: tuple[str, ...] | None = None
    error: str | None = None
```

- [ ] **Step 2: Write tests for serialization roundtrip**
- [ ] **Step 3: Run tests, commit**: `feat(core): AllModeEvent + CompoundEvent types for multi-backend chat`

---

## Task 2: ChatOrchestrator — Single Mode

**Files:**
- Create: `packages/core/src/ai_accounts_core/services/chat_orchestrator.py`
- Test: `packages/core/tests/services/test_chat_orchestrator.py`

- [ ] **Step 1: Create ChatOrchestrator with send_single()**

```python
# packages/core/src/ai_accounts_core/services/chat_orchestrator.py
from __future__ import annotations
import logging
from collections.abc import AsyncIterator
from ai_accounts_core.domain.chat import ChatMessage, ChatRole, ChatSession
from ai_accounts_core.protocols.backend import ChatRequest, ChatStreamEvent
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.scheduler import AccountScheduler

logger = logging.getLogger(__name__)

class ChatOrchestrator:
    def __init__(self, *, chat_service: ChatService, scheduler: AccountScheduler) -> None:
        self._chat = chat_service
        self._scheduler = scheduler

    async def send_single(
        self, *, session_id: str, content: str,
        backend_kind: str | None = None,
        account_id: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Single mode: pick best account (or use specified), stream response."""
        if account_id:
            # User specified a specific account
            async for event in self._chat.send_message(session_id=session_id, content=content):
                yield event
        else:
            # Auto-pick via scheduler
            result = await self._scheduler.pick(kind=backend_kind)
            if result is None:
                yield ChatStreamEvent(kind="error", payload="No accounts available")
                return
            # Use the picked account's session
            async for event in self._chat.send_message(session_id=session_id, content=content):
                yield event
```

- [ ] **Step 2: Write test with FakeBackend**
- [ ] **Step 3: Run tests, commit**: `feat(core): ChatOrchestrator — send_single with auto-scheduling`

---

## Task 3: ChatOrchestrator — All Mode (Parallel Fan-Out)

**Files:**
- Modify: `packages/core/src/ai_accounts_core/services/chat_orchestrator.py`
- Test: `packages/core/tests/services/test_chat_orchestrator_all.py`

- [ ] **Step 1: Add send_all() method**

Uses `asyncio.TaskGroup` to fan out to all READY backends in parallel. Each backend task pushes `AllModeEvent` items to an `asyncio.Queue`. The method reads from the queue and yields events.

```python
    async def send_all(
        self, *, session_id: str, content: str,
    ) -> AsyncIterator[AllModeEvent]:
        from ai_accounts_core.domain.chat_events import AllModeEvent
        health_list = await self._scheduler.get_all_health()
        ready = [h for h in health_list if h.rate_limited_until is None]
        if not ready:
            yield AllModeEvent(kind="backend_error", backend="all", error="No backends available")
            return

        queue: asyncio.Queue[AllModeEvent | None] = asyncio.Queue()
        pending = len(ready)

        async def call_one(health):
            nonlocal pending
            try:
                result = await self._scheduler.pick(kind=health.kind)
                if not result:
                    await queue.put(AllModeEvent(kind="backend_error", backend=health.kind, error="no account"))
                    return
                impl = self._scheduler._accounts._impl_for(health.kind)
                request = ChatRequest(messages=(...), model=result.kind)  # build from session
                async for event in impl.chat(request, result.credential, isolation_dir=Path(result.isolation_dir)):
                    if event.kind == "token":
                        await queue.put(AllModeEvent(kind="backend_delta", backend=health.kind, text=event.payload))
                    elif event.kind == "error":
                        await queue.put(AllModeEvent(kind="backend_error", backend=health.kind, error=event.payload))
                await queue.put(AllModeEvent(kind="backend_complete", backend=health.kind))
            except asyncio.TimeoutError:
                await queue.put(AllModeEvent(kind="backend_timeout", backend=health.kind))
            except Exception as exc:
                await queue.put(AllModeEvent(kind="backend_error", backend=health.kind, error=str(exc)))
            finally:
                pending -= 1
                if pending == 0:
                    await queue.put(None)  # sentinel

        async with asyncio.TaskGroup() as tg:
            for h in ready:
                tg.create_task(asyncio.wait_for(call_one(h), timeout=30.0))

        # Drain queue
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
```

- [ ] **Step 2: Write test — verify parallel fan-out with 2 FakeBackends**
- [ ] **Step 3: Run tests, commit**: `feat(core): ChatOrchestrator.send_all — parallel multi-backend fan-out`

---

## Task 4: ChatOrchestrator — Compound Mode (Parallel + Synthesis)

**Files:**
- Modify: `packages/core/src/ai_accounts_core/services/chat_orchestrator.py`
- Test: `packages/core/tests/services/test_chat_orchestrator_compound.py`

- [ ] **Step 1: Add send_compound() method**

Same fan-out as send_all, but after collecting all responses, builds a synthesis prompt and streams the synthesis via the primary backend.

```python
    async def send_compound(
        self, *, session_id: str, content: str,
        primary_kind: str | None = None,
    ) -> AsyncIterator[CompoundEvent]:
        # Phase 1: Fan out (same as send_all, collect responses)
        responses: dict[str, str] = {}
        async for event in self.send_all(session_id=session_id, content=content):
            # Forward as CompoundEvent
            yield CompoundEvent(kind=event.kind, backend=event.backend, text=event.text, error=event.error)
            if event.kind == "backend_delta" and event.text:
                responses.setdefault(event.backend, "")
                responses[event.backend] += event.text

        if not responses:
            yield CompoundEvent(kind="synthesis_error", error="No backend responses to synthesize")
            return

        # Phase 2: Synthesize
        primary = primary_kind or next(iter(responses))
        yield CompoundEvent(
            kind="synthesis_start",
            primary_backend=primary,
            backends_collected=tuple(responses.keys()),
        )

        synthesis_prompt = "Given these responses from multiple AI backends:\n\n"
        for backend, text in responses.items():
            synthesis_prompt += f"**{backend}:**\n{text}\n\n"
        synthesis_prompt += "Please synthesize a unified, comprehensive response."

        result = await self._scheduler.pick(kind=primary)
        if not result:
            yield CompoundEvent(kind="synthesis_error", error=f"No {primary} account available for synthesis")
            return

        impl = self._scheduler._accounts._impl_for(primary)
        synth_request = ChatRequest(
            messages=(ChatMessage(id="synth", session_id=session_id, role=ChatRole.USER,
                                  content=synthesis_prompt, created_at=_now()),),
            model=result.kind,
        )
        try:
            async for event in impl.chat(synth_request, result.credential, isolation_dir=Path(result.isolation_dir)):
                if event.kind == "token":
                    yield CompoundEvent(kind="synthesis_delta", text=event.payload)
            yield CompoundEvent(kind="synthesis_complete")
        except Exception as exc:
            yield CompoundEvent(kind="synthesis_error", error=str(exc))
```

- [ ] **Step 2: Write test — verify fan-out + synthesis flow**
- [ ] **Step 3: Run tests, commit**: `feat(core): ChatOrchestrator.send_compound — parallel + synthesis`

---

## Task 5: Litestar Chat Send Route (SSE)

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/chat_send.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Test: `packages/litestar/tests/test_chat_send.py`

- [ ] **Step 1: Create unified SSE endpoint**

```python
# POST /api/v1/chat/send → SSE stream
# Body: { session_id, content, mode: "single"|"all"|"compound", backend_kind?, account_id?, model? }

class _SendRequest(msgspec.Struct, kw_only=True):
    session_id: str
    content: str
    mode: str = "single"  # "single" | "all" | "compound"
    backend_kind: str | None = None
    account_id: str | None = None
    model: str | None = None

class ChatSendController(Controller):
    path = "/api/v1/chat"

    @post("/send")
    async def send(self, orchestrator: ChatOrchestrator, data: _SendRequest) -> Stream:
        if data.mode == "all":
            gen = orchestrator.send_all(session_id=data.session_id, content=data.content)
        elif data.mode == "compound":
            gen = orchestrator.send_compound(session_id=data.session_id, content=data.content, primary_kind=data.backend_kind)
        else:
            gen = orchestrator.send_single(session_id=data.session_id, content=data.content,
                                            backend_kind=data.backend_kind, account_id=data.account_id, model=data.model)

        async def sse():
            async for event in gen:
                yield f"event: chat\ndata: {msgspec.json.encode(event).decode()}\n\n"

        return Stream(sse(), media_type="text/event-stream",
                      headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] **Step 2: Wire ChatOrchestrator into app.py DI**
- [ ] **Step 3: Write route test — single mode SSE**
- [ ] **Step 4: Run tests, commit**: `feat(litestar): POST /api/v1/chat/send — unified SSE endpoint for single/all/compound`

---

## Task 6: TypeScript Types + SSE Parser + Client Methods

**Files:**
- Create: `packages/ts-core/src/types/smart-chat.ts`
- Create: `packages/ts-core/src/client/smart-chat-stream.ts`
- Modify: `packages/ts-core/src/client/index.ts`
- Modify: `packages/ts-core/src/index.ts`
- Test: `packages/ts-core/tests/smart-chat.test.ts`

- [ ] **Step 1: Create types**

```typescript
// packages/ts-core/src/types/smart-chat.ts
export interface BackendResponse {
  backend: string;
  content: string;
  status: 'streaming' | 'complete' | 'error' | 'timeout';
  error?: string;
}
export interface SynthesisState {
  status: 'waiting' | 'streaming' | 'complete' | 'error';
  content: string;
  primaryBackend: string;
  backendsCollected: string[];
  error?: string;
}
export interface BackendOption {
  kind: string;
  displayName: string;
  accounts: string[];
  models: string[];
}
export type SmartChatEvent =
  | { kind: 'token'; payload: string }
  | { kind: 'done'; payload: Record<string, unknown> }
  | { kind: 'error'; payload: string }
  | { kind: 'backend_delta'; backend: string; text: string }
  | { kind: 'backend_complete'; backend: string }
  | { kind: 'backend_error'; backend: string; error: string }
  | { kind: 'backend_timeout'; backend: string }
  | { kind: 'synthesis_start'; primary_backend: string; backends_collected: string[] }
  | { kind: 'synthesis_delta'; text: string }
  | { kind: 'synthesis_complete' }
  | { kind: 'synthesis_error'; error: string };
```

- [ ] **Step 2: Create SSE parser** (`smart-chat-stream.ts`)
- [ ] **Step 3: Add client methods**: `sendChat(sessionId, content, mode, opts)`, `createChatSession(backendId, model)`, `listChatSessions()`
- [ ] **Step 4: Update index.ts exports**
- [ ] **Step 5: Write tests, build, commit**: `feat(ts-core): smart chat types, SSE parser, and client methods`

---

## Task 7: useSmartChat + useSmartScroll Composables

**Files:**
- Create: `packages/vue-headless/src/composables/useSmartChat.ts`
- Create: `packages/vue-headless/src/composables/useSmartScroll.ts`
- Modify: `packages/vue-headless/src/index.ts`
- Test: `packages/vue-headless/tests/useSmartChat.test.ts`

- [ ] **Step 1: Create useSmartChat**

Full state machine: sessionId, messages, isStreaming, streamingContent, chatMode, backendResponses (Map), synthesisState, selectedBackend/Account/Model, availableBackends/Models.

Methods: createSession(), loadSession(), send(content), setMode(), selectBackend().

Dispatches SSE events to the right state: single-mode tokens go to streamingContent, all-mode events go to backendResponses map, compound events go to both + synthesisState.

- [ ] **Step 2: Create useSmartScroll**

Tracks scroll position of a container ref. `isNearBottom` = within 32px of bottom. `showScrollButton` = not near bottom. `scrollToBottom()` scrolls to bottom. Uses ResizeObserver + scroll listener.

- [ ] **Step 3: Update vue-headless exports**
- [ ] **Step 4: Write tests, commit**: `feat(vue-headless): useSmartChat + useSmartScroll composables`

---

## Task 8: Vue Styled Components (ChatBubble, ChatControls, ChatInput, AllModeResponses, CompoundSynthesis, AiChatPanel)

**Files:**
- Modify: `packages/vue-styled/package.json` (add marked + highlight.js)
- Create: `packages/vue-styled/src/components/ChatBubble.vue`
- Create: `packages/vue-styled/src/components/ChatControls.vue`
- Create: `packages/vue-styled/src/components/ChatInput.vue`
- Create: `packages/vue-styled/src/components/AllModeResponses.vue`
- Create: `packages/vue-styled/src/components/CompoundSynthesis.vue`
- Rewrite: `packages/vue-styled/src/components/AiChatPanel.vue`
- Modify: `packages/vue-styled/src/index.ts`
- Test: `packages/vue-styled/tests/AiChatPanel.test.ts`

- [ ] **Step 1: Add dependencies**

```bash
cd packages/vue-styled && pnpm add marked highlight.js
```

- [ ] **Step 2: Create ChatBubble.vue**

Props: role, content, backend?, timestamp?, streaming?. Renders markdown via `marked.parse(content)`. Code blocks get copy-to-clipboard buttons via post-render DOM walk. Avatar circle with role-based color (user=cyan, assistant=violet). Backend label when present. Timestamp in locale format.

- [ ] **Step 3: Create ChatControls.vue**

Props: backends (BackendOption[]), chatMode, selectedBackend, selectedModel. Emits: update:chatMode, update:selectedBackend, update:selectedModel. Four dropdowns/radio-groups: backend (auto + list), account (auto + emails), model (auto + list), mode (single/all/compound radio buttons). Account and model dropdowns disabled when backend is "auto" or no options. Selecting specific backend forces single mode.

- [ ] **Step 4: Create ChatInput.vue**

Props: placeholder?, disabled?, isStreaming?. Emits: send(content). Textarea with auto-expand (max 120px). Enter sends, Shift+Enter newlines. Send button (disabled when empty or streaming). Styled with dark theme matching AccountWizard.

- [ ] **Step 5: Create AllModeResponses.vue**

Props: responses (Map<string, BackendResponse>), collapsible?. Each backend gets a card with colored header (backend-specific colors: claude=violet, codex=green, gemini=blue, opencode=amber), status badge (streaming/complete/error/timeout), and markdown-rendered content.

- [ ] **Step 6: Create CompoundSynthesis.vue**

Props: state (SynthesisState). Badge: "Compound Synthesis via {primaryBackend}". Sources line. Markdown-rendered synthesis content. Loading/error states.

- [ ] **Step 7: Rewrite AiChatPanel.vue**

Main component. Uses `useSmartChat` + `useSmartScroll` internally.

Template structure:
- `density="detailed"`: `<ChatControls>` visible at top
- `density="minimal"`: no controls, auto-picks everything
- Message area with `<ChatBubble>` for each message
- `<AllModeResponses>` when in all/compound mode
- `<CompoundSynthesis>` when in compound mode
- Streaming indicator (typing dots) during single-mode streaming
- `<ChatInput>` at bottom
- Welcome screen when no messages
- Floating scroll-to-bottom button via `useSmartScroll`

- [ ] **Step 8: Update vue-styled index.ts exports**

Add: AiChatPanel, ChatBubble, ChatControls, ChatInput, AllModeResponses, CompoundSynthesis

- [ ] **Step 9: Write tests, build, commit**: `feat(vue-styled): AiChatPanel with markdown, controls, all-mode, compound synthesis`

---

## Task 9: Version Bump + Release

- [ ] **Step 1: Update CHANGELOG.md**
- [ ] **Step 2: Rebuild all frontend packages**
- [ ] **Step 3: Run full test suite**
- [ ] **Step 4: Commit**: `release: 0.5.0-alpha.1 (smart AI chat panel)`
