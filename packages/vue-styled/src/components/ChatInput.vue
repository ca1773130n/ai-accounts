<script setup lang="ts">
import { ref, watch, nextTick } from 'vue';

const props = withDefaults(defineProps<{
  placeholder?: string | undefined;
  disabled?: boolean;
  isStreaming?: boolean;
}>(), {
  placeholder: 'Type a message...',
});

const emit = defineEmits<{ send: [content: string] }>();
const input = ref('');
const textareaRef = ref<HTMLTextAreaElement | null>(null);

function handleSend() {
  const content = input.value.trim();
  if (!content || props.disabled || props.isStreaming) return;
  emit('send', content);
  input.value = '';
  nextTick(autoResize);
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}

function autoResize() {
  const el = textareaRef.value;
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

watch(input, () => nextTick(autoResize));
</script>

<template>
  <div class="aia-input">
    <textarea
      ref="textareaRef"
      v-model="input"
      class="aia-input__textarea"
      :placeholder="placeholder"
      rows="1"
      :disabled="disabled || isStreaming"
      @keydown="handleKeydown"
      @input="autoResize"
    />
    <button
      class="aia-input__send"
      :disabled="!input.trim() || disabled || isStreaming"
      @click="handleSend"
    >
      {{ isStreaming ? '...' : 'Send' }}
    </button>
  </div>
</template>

<style scoped>
.aia-input {
  display: flex; gap: var(--aia-space-2, 8px); padding: var(--aia-space-3, 12px);
  border-top: 1px solid var(--aia-border, #27272a); background: var(--aia-bg-elevated, #141414);
}
.aia-input__textarea {
  flex: 1; resize: none; padding: var(--aia-space-2, 8px) var(--aia-space-3, 12px);
  background: var(--aia-bg, #0a0a0a); color: var(--aia-fg, #fafafa);
  border: 1px solid var(--aia-border, #27272a); border-radius: var(--aia-radius, 8px);
  font-family: var(--aia-font-sans, system-ui, sans-serif); font-size: var(--aia-text-sm, 14px);
  line-height: 1.5; max-height: 120px; overflow-y: auto;
  transition: border-color var(--aia-transition, 150ms ease-out);
}
.aia-input__textarea:focus { outline: none; border-color: var(--aia-primary, #7c3aed); }
.aia-input__textarea::placeholder { color: var(--aia-fg-subtle, #71717a); }
.aia-input__textarea:disabled { opacity: 0.5; cursor: not-allowed; }
.aia-input__send {
  align-self: flex-end; padding: var(--aia-space-2, 8px) var(--aia-space-4, 16px);
  background: var(--aia-primary, #7c3aed); color: var(--aia-primary-fg, #fff);
  border: none; border-radius: var(--aia-radius, 8px); font-weight: 600;
  font-size: var(--aia-text-sm, 14px); cursor: pointer;
  transition: background var(--aia-transition, 150ms ease-out);
}
.aia-input__send:hover:not(:disabled) { background: var(--aia-primary-hover, #8b5cf6); }
.aia-input__send:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
