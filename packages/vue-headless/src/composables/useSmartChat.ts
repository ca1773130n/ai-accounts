import { ref, shallowRef, type Ref, type ShallowRef } from 'vue';
import type {
  ChatSessionDTO,
  ChatMessageDTO,
  SmartChatEvent,
  ChatMode,
  SendChatRequest,
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
}

const HEARTBEAT_TIMEOUT_MS = 65_000;

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

  let lastSeq = 0;
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;

  function clearHeartbeat() {
    if (heartbeatTimer) {
      clearTimeout(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function resetHeartbeat() {
    clearHeartbeat();
    heartbeatTimer = setTimeout(() => {
      error.value = 'Connection stale';
      isStreaming.value = false;
      heartbeatTimer = null;
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
    processGroups.clearGroups();
    lastSeq = 0;
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
      for await (const event of client.sendChat(req)) {
        dispatch(event);
      }
      // Stream ended — finalize
      if (chatMode.value === 'single' && streamingContent.value) {
        const assistantMsg: ChatMessageDTO = {
          id: `msg-${Date.now()}`, role: 'assistant', content: streamingContent.value,
          created_at: new Date().toISOString(), model: null, tokens_in: null, tokens_out: null,
        };
        messages.value = [...messages.value, assistantMsg];
      }
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Chat failed';
    } finally {
      clearHeartbeat();
      isStreaming.value = false;
      streamingContent.value = '';
    }
  }

  function dispatch(event: SmartChatEvent) {
    // Seq-based dedup: skip replays / already-seen events.
    if (typeof event._seq === 'number') {
      if (event._seq <= lastSeq) return;
      lastSeq = event._seq;
    }
    // Heartbeat reset on every live event.
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
      case 'tool_call':
        processGroups.processToolCallDelta({
          id: event.id,
          name: event.name,
          arguments: event.arguments,
          group_type: event.group_type,
        });
        break;

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
  };
}
