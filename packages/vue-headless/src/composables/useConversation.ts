import { ref, shallowRef, type Ref, type ShallowRef } from 'vue';
import type { AiAccountsClient } from '@ai-accounts/ts-core';

export interface ChatMessageDTO {
  id: string;
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  created_at: string;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
}

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
    const session = await (client as any).createConversation({ backend_id: backendId, model });
    sessionId.value = session.id;
    messages.value = [];
  }

  async function load(id: string) {
    error.value = null;
    const detail = await (client as any).getConversation(id);
    sessionId.value = detail.id;
    messages.value = detail.messages;
  }

  async function send(content: string) {
    if (!sessionId.value) { error.value = 'No active session'; return; }
    error.value = null;
    isStreaming.value = true;
    streamingText.value = '';
    const userMsg: ChatMessageDTO = {
      id: `pending-${Date.now()}`, role: 'user', content,
      created_at: new Date().toISOString(), model: null, tokens_in: null, tokens_out: null,
    };
    messages.value = [...messages.value, userMsg];
    try {
      let accumulated = '';
      for await (const delta of (client as any).streamChat(sessionId.value, content)) {
        if (delta.kind === 'token' && delta.text) {
          accumulated += delta.text;
          streamingText.value = accumulated;
        } else if (delta.kind === 'error') {
          error.value = delta.text ?? 'Unknown error';
        }
      }
      if (accumulated) {
        const assistantMsg: ChatMessageDTO = {
          id: `msg-${Date.now()}`, role: 'assistant', content: accumulated,
          created_at: new Date().toISOString(), model: null, tokens_in: null, tokens_out: null,
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
