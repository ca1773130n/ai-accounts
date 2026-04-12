<script setup lang="ts">
import { ref, nextTick, watch } from 'vue';
import ChatMessage from './ChatMessage.vue';

const props = defineProps<{
  messages: Array<{ id: string; role: 'user' | 'assistant' | 'system'; content: string; model?: string | null; tokens_in?: number | null; tokens_out?: number | null; }>;
  streamingText?: string;
  isStreaming?: boolean;
  disabled?: boolean;
}>();
const emit = defineEmits<{ send: [content: string] }>();
const input = ref('');
const messagesEnd = ref<HTMLElement | null>(null);

function handleSend() {
  const content = input.value.trim();
  if (!content || props.disabled || props.isStreaming) return;
  emit('send', content);
  input.value = '';
}
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
}
watch(() => props.messages.length, () => nextTick(() => messagesEnd.value?.scrollIntoView({ behavior: 'smooth' })));
</script>
<template>
  <div class="aia-chat-panel">
    <div class="aia-chat-panel__messages">
      <ChatMessage v-for="msg in messages" :key="msg.id" :role="msg.role" :content="msg.content" :model="msg.model || undefined" :tokens-in="msg.tokens_in || undefined" :tokens-out="msg.tokens_out || undefined" />
      <ChatMessage v-if="isStreaming && streamingText" role="assistant" :content="streamingText" :streaming="true" />
      <div ref="messagesEnd" />
    </div>
    <div class="aia-chat-panel__input">
      <textarea v-model="input" class="aia-chat-panel__textarea" placeholder="Type a message..." rows="2" :disabled="disabled || isStreaming" @keydown="handleKeydown" />
      <button class="aia-chat-panel__send" :disabled="!input.trim() || disabled || isStreaming" @click="handleSend">Send</button>
    </div>
  </div>
</template>
<style scoped>
.aia-chat-panel { display: flex; flex-direction: column; height: 100%; font-family: var(--aia-font-sans, system-ui, sans-serif); }
.aia-chat-panel__messages { flex: 1; overflow-y: auto; padding: var(--aia-space-3, 12px); }
.aia-chat-panel__input { display: flex; gap: var(--aia-space-2, 8px); padding: var(--aia-space-3, 12px); border-top: 1px solid var(--aia-color-border, #e0e0e0); }
.aia-chat-panel__textarea { flex: 1; resize: none; padding: var(--aia-space-2, 8px); border: 1px solid var(--aia-color-border, #e0e0e0); border-radius: var(--aia-radius-md, 8px); font-family: inherit; font-size: var(--aia-text-sm, 14px); }
.aia-chat-panel__send { padding: var(--aia-space-2, 8px) var(--aia-space-4, 16px); background: var(--aia-color-primary, #2563eb); color: white; border: none; border-radius: var(--aia-radius-md, 8px); cursor: pointer; font-weight: 500; }
.aia-chat-panel__send:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
