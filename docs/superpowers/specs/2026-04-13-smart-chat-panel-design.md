# Smart AI Chat Panel Design Spec

**Date:** 2026-04-13
**Status:** Approved
**Goal:** Ship a complete, drop-in `<AiChatPanel />` component that handles backend selection, streaming chat, multi-backend modes, and compound synthesis — so consumers just mount it and get a working AI chat with automatic account scheduling.

---

## Overview

Extract Agented's "All Backends" page chat features into the ai-accounts package as reusable components. Consumers mount `<AiChatPanel />` with a `density` prop and get everything: auto-scheduling, streaming markdown, multi-backend parallel/compound modes.

**Reference:** Agented's `AIBackendsPage.vue`, `AiChatPanel.vue`, `useAiChat.ts`, `useAllMode.ts`, `CLIProxyChatService`, `AllModeService`, `CompoundModeService`

---

## Tiers

### Tier 1 — Core (this milestone)
- Rich chat panel with streaming markdown (marked + highlight.js, not smd.js — simpler, no native deps)
- Smart scroll (auto-scroll when near bottom, float button when scrolled up)
- Account/model/backend selector bar with auto-pick via `AccountScheduler`
- `density="minimal"` (just chat + auto) / `density="detailed"` (selectors visible)
- Session management (create, list, load history)
- Message bubbles with avatars, timestamps, markdown, code copy buttons
- SSE streaming with reconnection support

### Tier 2 — Power features (this milestone)
- **All mode:** Fan out to all backends in parallel, show responses side-by-side with backend-colored headers
- **Compound mode:** Fan out + synthesize via primary backend, show both individual + unified response
- Mode selector (Single / All / Compound) in the controls bar

### NOT in scope
- Process groups (tool calls, reasoning) — consumer-specific
- Finalization banners — consumer-specific
- smd.js streaming markdown — too complex, use marked instead
- Super-agent integration — that's Agented-specific

---

## Component Architecture

```
<AiChatPanel>                     (vue-styled, main entry)
├── <ChatControls>                (backend/account/model/mode selectors)
├── <ChatMessages>                (scrollable message area)
│   ├── <ChatBubble> × N          (individual messages)
│   ├── <AllModeResponses>        (parallel backend responses)
│   └── <CompoundSynthesis>       (synthesis result)
├── <StreamingIndicator>          (typing dots during streaming)
└── <ChatInput>                   (textarea + send button)
```

### Props

```typescript
interface AiChatPanelProps {
  density?: 'minimal' | 'detailed';  // default: 'minimal'
  defaultBackend?: string;           // e.g., 'claude' — preselect
  defaultModel?: string;             // preselect model
  placeholder?: string;              // input placeholder text
  welcomeTitle?: string;             // welcome screen title
  welcomeSubtitle?: string;          // welcome screen subtitle
  readOnly?: boolean;                // hide input, just show messages
}
```

### Emits

```typescript
'message-sent': (content: string) => void
'session-created': (sessionId: string) => void
'error': (error: string) => void
```

---

## Backend: Chat Orchestration Service

New service in `ai-accounts-core` that wraps `ChatService` + `AccountScheduler` + CLIProxyAPI routing:

### `services/chat_orchestrator.py`

```python
class ChatOrchestrator:
    """High-level chat service that auto-picks accounts and handles modes."""

    async def send_single(
        self, session_id: str, content: str,
        backend_kind: str | None = None,
        account_id: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Single mode: pick best account (or use specified), stream response."""

    async def send_all(
        self, session_id: str, content: str,
    ) -> AsyncIterator[AllModeEvent]:
        """All mode: fan out to all READY backends in parallel."""

    async def send_compound(
        self, session_id: str, content: str,
        primary_kind: str | None = None,
    ) -> AsyncIterator[CompoundModeEvent]:
        """Compound mode: fan out + synthesize via primary backend."""
```

### Event Types

```python
# Single mode — same ChatStreamEvent as before (token, done, error)

# All mode
class AllModeEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str  # "backend_delta" | "backend_complete" | "backend_error" | "backend_timeout"
    backend: str  # "claude", "codex", etc.
    text: str | None = None
    error: str | None = None

# Compound mode — AllModeEvent + synthesis events
class CompoundEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str  # AllModeEvent kinds + "synthesis_start" | "synthesis_delta" | "synthesis_complete" | "synthesis_error"
    backend: str | None = None
    text: str | None = None
    primary_backend: str | None = None
    backends_collected: tuple[str, ...] | None = None
    error: str | None = None
```

### Litestar Routes

```
POST /api/v1/chat/send                    → SSE stream
     Body: { session_id, content, mode: "single"|"all"|"compound",
             backend_kind?, account_id?, model? }

GET  /api/v1/chat/sessions                → list sessions
POST /api/v1/chat/sessions                → create session
GET  /api/v1/chat/sessions/{id}           → get session with messages
```

---

## Frontend: Composables

### `useSmartChat` (vue-headless)

Replaces `useConversation`. Manages the full chat lifecycle:

```typescript
interface UseSmartChat {
  // State
  sessionId: Ref<string | null>;
  messages: ShallowRef<ChatMessageDTO[]>;
  isStreaming: Ref<boolean>;
  streamingContent: Ref<string>;
  error: Ref<string | null>;
  chatMode: Ref<'single' | 'all' | 'compound'>;

  // Multi-backend state (all/compound modes)
  backendResponses: Ref<Map<string, BackendResponse>>;
  synthesisState: Ref<SynthesisState | null>;

  // Controls state
  selectedBackend: Ref<string | null>;  // null = auto
  selectedAccount: Ref<string | null>;
  selectedModel: Ref<string | null>;
  availableBackends: Ref<BackendOption[]>;
  availableModels: Ref<string[]>;

  // Methods
  createSession: () => Promise<void>;
  loadSession: (id: string) => Promise<void>;
  send: (content: string) => Promise<void>;
  setMode: (mode: 'single' | 'all' | 'compound') => void;
  selectBackend: (kind: string | null) => void;
}
```

### `useSmartScroll` (vue-headless)

```typescript
interface UseSmartScroll {
  containerRef: Ref<HTMLElement | null>;
  isNearBottom: Ref<boolean>;
  showScrollButton: Ref<boolean>;
  scrollToBottom: () => void;
}
```

---

## Frontend: Styled Components

### `AiChatPanel.vue` (vue-styled)

The main component. Uses `useSmartChat` internally.

**density="minimal":**
- No controls bar — auto-picks everything via scheduler
- Just messages + input
- Mode defaults to "single"

**density="detailed":**
- Controls bar visible: backend dropdown, account dropdown, model dropdown, mode radio buttons
- Backend "Auto" uses scheduler, specific backend bypasses it

### `ChatControls.vue`

Backend/account/model/mode selector bar. Only rendered when `density="detailed"`.

### `ChatBubble.vue`

Single message. Renders markdown via `marked`. Code blocks get copy buttons. Avatar with role-based color. Timestamp.

### `AllModeResponses.vue`

Shows parallel backend responses with colored headers. Collapsible in compound mode.

### `CompoundSynthesis.vue`

Shows the synthesis result from compound mode. Badge showing primary backend and sources.

### `ChatInput.vue`

Textarea + send button. Auto-expand. Enter to send, Shift+Enter for newline.

---

## Streaming Markdown

Use `marked` (already widely used, no native deps) + `highlight.js` for code highlighting. Not smd.js (requires native build, complex).

For streaming: accumulate tokens, re-render via `marked.parse()` on each token (fast enough for chat — marked is <1ms per parse). Add code copy button wiring after each render via `MutationObserver`.

---

## Multi-Backend Fan-Out (Backend)

### All Mode

```python
async def send_all(self, session_id, content):
    backends = await self._scheduler.get_all_health()
    ready = [h for h in backends if h.rate_limited_until is None]

    async def call_backend(health):
        try:
            result = await self._scheduler.pick(kind=health.kind)
            if not result:
                yield AllModeEvent(kind="backend_error", backend=health.kind, error="no account available")
                return
            async for event in impl.chat(request, result.credential, isolation_dir=...):
                if event.kind == "token":
                    yield AllModeEvent(kind="backend_delta", backend=health.kind, text=event.payload)
            yield AllModeEvent(kind="backend_complete", backend=health.kind)
        except Exception as exc:
            yield AllModeEvent(kind="backend_error", backend=health.kind, error=str(exc))

    # Fan out with asyncio.TaskGroup, merge events
    async with asyncio.TaskGroup() as tg:
        for h in ready:
            tg.create_task(call_backend(h))
```

### Compound Mode

Same as All Mode, plus a synthesis step:
1. Collect all backend responses
2. Build synthesis prompt: "Given these responses from multiple backends: ..."
3. Stream synthesis via primary backend
4. Emit `synthesis_start`, `synthesis_delta`, `synthesis_complete`

---

## TypeScript Types

### `types/smart-chat.ts`

```typescript
interface BackendResponse {
  backend: string;
  content: string;
  status: 'streaming' | 'complete' | 'error' | 'timeout';
  error?: string;
}

interface SynthesisState {
  status: 'waiting' | 'streaming' | 'complete' | 'error';
  content: string;
  primaryBackend: string;
  backendsCollected: string[];
  error?: string;
}

interface BackendOption {
  kind: string;
  displayName: string;
  accounts: string[];
  models: string[];
}

// SSE event types for multi-backend
interface AllModeEventDTO {
  kind: 'backend_delta' | 'backend_complete' | 'backend_error' | 'backend_timeout';
  backend: string;
  text?: string;
  error?: string;
}

interface CompoundEventDTO extends AllModeEventDTO {
  kind: AllModeEventDTO['kind'] | 'synthesis_start' | 'synthesis_delta' | 'synthesis_complete' | 'synthesis_error';
  primary_backend?: string;
  backends_collected?: string[];
}
```

---

## Dependencies

### New
- `marked` — markdown rendering (MIT, zero deps, ~50KB)
- `highlight.js` — code highlighting (BSD, ~300KB with common languages)

### Existing (already in package)
- `httpx` — HTTP client for CLIProxyAPI
- `msgspec` — event serialization
- `@xterm/xterm` — already added for TerminalView

---

## Testing Strategy

### Backend
- `test_chat_orchestrator.py` — single/all/compound modes with FakeBackend
- All mode: verify parallel fan-out, timeout handling, error propagation
- Compound mode: verify synthesis prompt construction, streaming

### Frontend
- `ChatBubble.test.ts` — markdown rendering, code copy, avatar
- `ChatControls.test.ts` — backend/model selection, mode switching
- `AiChatPanel.test.ts` — end-to-end with mock client
- `useSmartChat.test.ts` — state transitions, mode switching

---

## What consumers do

```vue
<!-- Minimal: just drop it in -->
<AiChatPanel density="minimal" />

<!-- Detailed: with selectors -->
<AiChatPanel
  density="detailed"
  default-backend="claude"
  welcome-title="Chat with AI"
  placeholder="Ask anything..."
/>

<!-- Read-only: show conversation history -->
<AiChatPanel :session-id="existingSession" read-only />
```

No route wiring. No chat service setup. The component uses `useAiAccounts()` (injected by the plugin) to access the client, which hits the package's own routes.
