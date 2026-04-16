import { ref, shallowRef, type Ref, type ShallowRef } from 'vue';
import type {
  ChatSessionDTO,
  ChatMessageDTO,
  SmartChatEvent,
  ChatMode,
  SendChatRequest,
  ToolCallDelta,
} from '@ai-accounts/ts-core';
import { useAiAccounts } from './useAiAccounts';
import { useProcessGroups, type UseProcessGroupsReturn } from './useProcessGroups';

export interface BackendResponseState {
  backend: string;
  content: string;
  status: 'streaming' | 'complete' | 'error' | 'timeout';
  error?: string;
}

export interface SynthesisStateRef {
  status: 'waiting' | 'streaming' | 'complete' | 'error';
  content: string;
  primaryBackend: string;
  backendsCollected: string[];
  error?: string;
}

export interface UseSmartChatReturn {
  sessionId: Ref<string | null>;
  messages: ShallowRef<ChatMessageDTO[]>;
  isStreaming: Ref<boolean>;
  streamingContent: Ref<string>;
  error: Ref<string | null>;
  chatMode: Ref<ChatMode>;
  backendResponses: Ref<Map<string, BackendResponseState>>;
  synthesisState: Ref<SynthesisStateRef | null>;
  selectedBackend: Ref<string | null>;
  selectedAccount: Ref<string | null>;
  selectedModel: Ref<string | null>;
  createSession: (backendId: string, model: string) => Promise<void>;
  loadSession: (id: string) => Promise<void>;
  send: (content: string) => Promise<void>;
  setMode: (mode: ChatMode) => void;
  selectBackend: (kind: string | null) => void;
  processGroups: UseProcessGroupsReturn;
  canFinalize: Ref<boolean>;
  isFinalizing: Ref<boolean>;
  detectedConfig: Ref<Record<string, unknown> | null>;
  finalize: () => Promise<Record<string, unknown> | null>;
  setConfigParser: (parser: ((content: string) => Record<string, unknown> | null) | null) => void;
}

const HEARTBEAT_TIMEOUT_MS = 90_000;

export function useSmartChat(): UseSmartChatReturn {
  const { client } = useAiAccounts();

  const sessionId = ref<string | null>(null);
  const messages = shallowRef<ChatMessageDTO[]>([]);
  const isStreaming = ref(false);
  const streamingContent = ref('');
  const error = ref<string | null>(null);
  const chatMode = ref<ChatMode>('single');
  const backendResponses = ref(new Map<string, BackendResponseState>());
  const synthesisState = ref<SynthesisStateRef | null>(null);
  const selectedBackend = ref<string | null>(null);
  const selectedAccount = ref<string | null>(null);
  const selectedModel = ref<string | null>(null);
  const processGroups = useProcessGroups();

  const canFinalize = ref(false);
  const isFinalizing = ref(false);
  const detectedConfig = ref<Record<string, unknown> | null>(null);
  let configParser: ((content: string) => Record<string, unknown> | null) | null = null;

  function setConfigParser(parser: ((content: string) => Record<string, unknown> | null) | null) {
    configParser = parser;
  }

  /**
   * Returns the parsed config for the host to act on. This composable
   * performs no persistence — the `isFinalizing` flag is exposed so hosts
   * can drive a spinner around their own save call.
   */
  async function finalize(): Promise<Record<string, unknown> | null> {
    if (!canFinalize.value) return null;
    isFinalizing.value = true;
    try {
      return detectedConfig.value;
    } finally {
      isFinalizing.value = false;
    }
  }

  let lastSeq = 0;
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  let activeAbort: AbortController | null = null;

  function clearHeartbeat() {
    if (heartbeatTimer) {
      clearTimeout(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function resetHeartbeat() {
    clearHeartbeat();
    heartbeatTimer = setTimeout(() => {
      error.value = 'Connection lost — no activity from server';
      isStreaming.value = false;
      heartbeatTimer = null;
      if (activeAbort) {
        activeAbort.abort(new DOMException('heartbeat-timeout', 'AbortError'));
      }
    }, HEARTBEAT_TIMEOUT_MS);
  }

  async function createSession(backendId: string, model: string) {
    error.value = null;
    const session = await client.createChatSession(backendId, model);
    sessionId.value = session.id;
    messages.value = [];
  }

  async function loadSession(id: string) {
    error.value = null;
    const detail = await (client as any).getConversation(id);
    sessionId.value = detail.id;
    messages.value = detail.messages;
  }

  async function send(content: string) {
    if (!sessionId.value) { error.value = 'No active session'; return; }
    error.value = null;
    isStreaming.value = true;
    streamingContent.value = '';
    backendResponses.value = new Map();
    synthesisState.value = null;
    canFinalize.value = false;
    detectedConfig.value = null;
    processGroups.clearGroups();
    lastSeq = 0;
    activeAbort = new AbortController();
    resetHeartbeat();

    // Add user message optimistically
    const userMsg: ChatMessageDTO = {
      id: `pending-${Date.now()}`, role: 'user', content,
      created_at: new Date().toISOString(), model: null, tokens_in: null, tokens_out: null,
    };
    messages.value = [...messages.value, userMsg];

    try {
      const req: SendChatRequest = { session_id: sessionId.value, content, mode: chatMode.value };
      if (selectedBackend.value) req.backend_kind = selectedBackend.value;
      if (selectedAccount.value) req.account_id = selectedAccount.value;
      if (selectedModel.value) req.model = selectedModel.value;
      for await (const event of client.sendChat(req, { signal: activeAbort.signal })) {
        dispatch(event);
      }
      // Stream ended — commit assistant message to history
      if (chatMode.value === 'single' && streamingContent.value) {
        const assistantMsg: ChatMessageDTO = {
          id: `msg-${Date.now()}`, role: 'assistant', content: streamingContent.value,
          created_at: new Date().toISOString(), model: null, tokens_in: null, tokens_out: null,
        };
        messages.value = [...messages.value, assistantMsg];
      }
      if (configParser) {
        const lastMsg = messages.value[messages.value.length - 1];
        if (lastMsg && lastMsg.role === 'assistant') {
          try {
            const cfg = configParser(lastMsg.content);
            if (cfg) {
              detectedConfig.value = cfg;
              canFinalize.value = true;
            }
          } catch (e) {
            // eslint-disable-next-line no-console
            console.error('[useSmartChat] configParser threw — canFinalize stays false', e);
          }
        }
      }
    } catch (e: unknown) {
      // Heartbeat-triggered aborts already set a user-visible message; don't overwrite.
      if (e instanceof DOMException && e.name === 'AbortError') {
        // leave error.value as set by the heartbeat watchdog
      } else if (e instanceof Error) {
        error.value = `${e.name}: ${e.message}`;
      } else {
        error.value = `Chat failed: ${String(e)}`;
      }
    } finally {
      clearHeartbeat();
      activeAbort = null;
      isStreaming.value = false;
      streamingContent.value = '';
    }
  }

  function dispatch(event: SmartChatEvent) {
    // Seq-based dedup: skip replays / already-seen events.
    if (typeof event._seq === 'number') {
      if (event._seq <= lastSeq) return;
      if (lastSeq > 0 && event._seq > lastSeq + 1) {
        // eslint-disable-next-line no-console
        console.warn(
          '[useSmartChat] seq gap detected: lastSeq=%d incoming=%d (lost %d events)',
          lastSeq,
          event._seq,
          event._seq - lastSeq - 1,
        );
      }
      lastSeq = event._seq;
    }
    resetHeartbeat();
    // Terminal events should stop the heartbeat watchdog.
    if (
      event.kind === 'done' ||
      event.kind === 'error' ||
      event.kind === 'synthesis_complete' ||
      event.kind === 'synthesis_error'
    ) {
      clearHeartbeat();
    }
    switch (event.kind) {
      // Single mode
      case 'token':
        streamingContent.value += event.payload;
        break;
      case 'done':
        break;
      case 'error':
        error.value = event.payload ?? 'Unknown error';
        break;
      case 'tool_call': {
        const delta: ToolCallDelta = { id: event.id };
        if (event.name !== undefined) delta.name = event.name;
        if (event.arguments !== undefined) delta.arguments = event.arguments;
        if (event.group_type !== undefined) delta.group_type = event.group_type;
        processGroups.processToolCallDelta(delta);
        break;
      }

      // All/compound mode — backend events
      case 'backend_delta': {
        const existing = backendResponses.value.get(event.backend);
        const updated = new Map(backendResponses.value);
        updated.set(event.backend, {
          backend: event.backend,
          content: (existing?.content ?? '') + (event.text ?? ''),
          status: 'streaming',
        });
        backendResponses.value = updated;
        break;
      }
      case 'backend_complete': {
        const existing = backendResponses.value.get(event.backend);
        if (existing) {
          const updated = new Map(backendResponses.value);
          updated.set(event.backend, { ...existing, status: 'complete' });
          backendResponses.value = updated;
        }
        break;
      }
      case 'backend_error': {
        const existing = backendResponses.value.get(event.backend);
        const updated = new Map(backendResponses.value);
        updated.set(event.backend, {
          backend: event.backend,
          content: existing?.content ?? '',
          status: 'error',
          error: event.error,
        });
        backendResponses.value = updated;
        break;
      }
      case 'backend_timeout': {
        const existing = backendResponses.value.get(event.backend);
        const updated = new Map(backendResponses.value);
        updated.set(event.backend, {
          backend: event.backend,
          content: existing?.content ?? '',
          status: 'timeout',
        });
        backendResponses.value = updated;
        break;
      }

      // Compound synthesis
      case 'synthesis_start': {
        synthesisState.value = {
          status: 'streaming', content: '',
          primaryBackend: event.primary_backend,
          backendsCollected: event.backends_collected ?? [],
        };
        break;
      }
      case 'synthesis_delta': {
        if (synthesisState.value) {
          synthesisState.value = {
            ...synthesisState.value,
            content: synthesisState.value.content + (event.text ?? ''),
          };
        }
        break;
      }
      case 'synthesis_complete':
        if (synthesisState.value) {
          synthesisState.value = { ...synthesisState.value, status: 'complete' };
        }
        break;
      case 'synthesis_error': {
        if (synthesisState.value) {
          synthesisState.value = { ...synthesisState.value, status: 'error', error: event.error };
        } else {
          synthesisState.value = {
            status: 'error', content: '', primaryBackend: '', backendsCollected: [],
            error: event.error,
          };
        }
        break;
      }
    }
  }

  function setMode(mode: ChatMode) { chatMode.value = mode; }
  function selectBackend(kind: string | null) {
    selectedBackend.value = kind;
    selectedAccount.value = null;
    selectedModel.value = null;
  }

  return {
    sessionId, messages, isStreaming, streamingContent, error, chatMode,
    backendResponses, synthesisState, selectedBackend, selectedAccount, selectedModel,
    createSession, loadSession, send, setMode, selectBackend,
    processGroups,
    canFinalize, isFinalizing, detectedConfig, finalize, setConfigParser,
  };
}
