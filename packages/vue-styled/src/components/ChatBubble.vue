<script setup lang="ts">
import { computed } from 'vue';
import { marked } from 'marked';
import hljs from 'highlight.js';
import MessageActions from './MessageActions.vue';

interface MessageLike {
  role: string;
  content: string;
  created_at?: string;
}

// marked v13+ dropped the highlight option; use a custom renderer instead
const renderer: import('marked').RendererObject = {
  code({ text, lang }: { text: string; lang?: string }) {
    let highlighted: string;
    if (lang && hljs.getLanguage(lang)) {
      highlighted = hljs.highlight(text, { language: lang }).value;
    } else {
      highlighted = hljs.highlightAuto(text).value;
    }
    const langAttr = lang ? ` class="language-${lang}"` : '';
    return `<pre><code${langAttr}>${highlighted}</code></pre>`;
  },
};
marked.use({ renderer });

const props = defineProps<{
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  backend?: string | null;
  timestamp?: string | null;
  streaming?: boolean;
  showActions?: boolean;
  allMessages?: MessageLike[];
}>();

const html = computed(() => marked.parse(props.content || '') as string);
const timeStr = computed(() => {
  if (!props.timestamp) return '';
  try { return new Date(props.timestamp).toLocaleTimeString(); } catch { return ''; }
});

function copyCode(e: Event) {
  const btn = (e.target as HTMLElement).closest('.aia-copy-btn');
  if (!btn) return;
  const pre = btn.closest('.aia-code-block')?.querySelector('code');
  if (pre) navigator.clipboard.writeText(pre.textContent || '');
}
</script>

<template>
  <div class="aia-bubble" :class="[`aia-bubble--${role}`, { 'aia-bubble--streaming': streaming }]">
    <div class="aia-bubble__avatar">{{ role === 'user' ? 'U' : role === 'tool' ? 'T' : 'AI' }}</div>
    <div class="aia-bubble__body">
      <div class="aia-bubble__header">
        <span class="aia-bubble__role">{{ role }}</span>
        <span v-if="backend" class="aia-bubble__backend">{{ backend }}</span>
        <span v-if="timeStr" class="aia-bubble__time">{{ timeStr }}</span>
      </div>
      <div class="aia-bubble__content" @click="copyCode" v-html="html" />
    </div>
    <MessageActions
      v-if="showActions"
      :content="content"
      v-bind="allMessages !== undefined ? { allMessages } : {}"
    />
  </div>
</template>

<style scoped>
.aia-bubble { display: flex; gap: 0.75rem; padding: 0.75rem 0; position: relative; }
.aia-bubble:hover :deep(.message-actions) { opacity: 1; }
.aia-bubble--user { flex-direction: row-reverse; }
.aia-bubble__avatar {
  width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem; font-weight: 700; flex-shrink: 0;
}
.aia-bubble--user .aia-bubble__avatar { background: rgba(96,165,250,0.2); color: var(--accent-cyan, #60a5fa); }
.aia-bubble--assistant .aia-bubble__avatar { background: rgba(124,58,237,0.2); color: var(--accent-violet, #8b5cf6); }
.aia-bubble--system .aia-bubble__avatar { background: rgba(113,113,122,0.2); color: var(--aia-fg-subtle, #71717a); }
.aia-bubble--tool .aia-bubble__avatar { background: rgba(16,185,129,0.2); color: var(--aia-success, #10b981); }
.aia-bubble__body { flex: 1; min-width: 0; }
.aia-bubble__header { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem; }
.aia-bubble__role { font-size: var(--aia-text-xs, 12px); font-weight: 600; text-transform: capitalize; color: var(--aia-fg-muted, #a1a1aa); }
.aia-bubble__backend { font-size: 0.65rem; padding: 1px 6px; border-radius: var(--aia-radius-sm, 4px); background: var(--aia-bg-hover, #1f1f1f); color: var(--aia-fg-subtle, #71717a); }
.aia-bubble__time { font-size: 0.65rem; color: var(--aia-fg-subtle, #71717a); margin-left: auto; }
.aia-bubble__content { font-size: var(--aia-text-sm, 14px); line-height: 1.6; color: var(--aia-fg, #fafafa); }
.aia-bubble__content :deep(pre) { background: var(--aia-bg, #0a0a0a); border-radius: var(--aia-radius, 8px); padding: 0.75rem; overflow-x: auto; margin: 0.5rem 0; font-size: 0.8rem; }
.aia-bubble__content :deep(code) { font-family: var(--aia-font-mono, monospace); }
.aia-bubble__content :deep(p) { margin: 0.25rem 0; }
.aia-bubble--streaming .aia-bubble__content::after { content: '\25AE'; animation: aia-blink 1s step-end infinite; }
@keyframes aia-blink { 50% { opacity: 0; } }
</style>
