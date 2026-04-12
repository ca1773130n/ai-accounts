<script setup lang="ts">
defineProps<{
  role: 'user' | 'assistant' | 'system';
  content: string;
  model?: string | null | undefined;
  tokensIn?: number | null | undefined;
  tokensOut?: number | null | undefined;
  streaming?: boolean;
}>();
</script>
<template>
  <div class="aia-chat-message" :class="[`aia-chat-message--${role}`, { 'aia-chat-message--streaming': streaming }]">
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
.aia-chat-message { padding: var(--aia-space-3, 12px); border-radius: var(--aia-radius-md, 8px); margin-bottom: var(--aia-space-2, 8px); }
.aia-chat-message--user { background: var(--aia-color-surface-alt, #f0f0f0); margin-left: var(--aia-space-6, 48px); }
.aia-chat-message--assistant { background: var(--aia-color-surface, #fff); border: 1px solid var(--aia-color-border, #e0e0e0); margin-right: var(--aia-space-6, 48px); }
.aia-chat-message__role { font-size: var(--aia-text-xs, 11px); font-weight: 600; text-transform: uppercase; color: var(--aia-color-text-muted, #888); margin-bottom: var(--aia-space-1, 4px); }
.aia-chat-message__content { white-space: pre-wrap; word-break: break-word; line-height: 1.5; }
.aia-chat-message__meta { font-size: var(--aia-text-xs, 11px); color: var(--aia-color-text-muted, #888); margin-top: var(--aia-space-1, 4px); display: flex; gap: var(--aia-space-2, 8px); }
.aia-chat-message--streaming .aia-chat-message__content::after { content: '\25AE'; animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }
</style>
