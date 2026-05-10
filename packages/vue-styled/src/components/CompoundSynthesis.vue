<script setup lang="ts">
import { computed } from 'vue';
import { marked } from 'marked';
import type { SynthesisStateRef } from '@ai-accounts/vue-headless';

interface Props {
  state: SynthesisStateRef;
  /**
   * When true, prepend a sparkle (✨) glyph before the
   * "Compound Synthesis" label. Default `false`.
   * Back-migrated from Agented.
   */
  sparkleIcon?: boolean;
  /**
   * When true, render a pulsing placeholder body
   * ("Generating synthesis..." / "Waiting for backend responses...")
   * while `state.content` is empty and the status is `streaming` or
   * `waiting`. Default `false` preserves the upstream behavior of
   * showing an empty content box.
   * Back-migrated from Agented.
   */
  loadingPlaceholders?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  sparkleIcon: false,
  loadingPlaceholders: false,
});

const html = computed(() => marked.parse(props.state.content || '') as string);
const isStreaming = computed(() => props.state.status === 'streaming');
const hasContent = computed(() => Boolean(props.state.content && props.state.content.length > 0));
/** Show the back-migrated pulsing placeholder text. */
const showPlaceholder = computed(
  () =>
    props.loadingPlaceholders &&
    !hasContent.value &&
    (props.state.status === 'streaming' || props.state.status === 'waiting'),
);
const placeholderText = computed(() =>
  props.state.status === 'streaming'
    ? 'Generating synthesis...'
    : 'Waiting for backend responses...',
);

function statusBadge(status: SynthesisStateRef['status']) {
  switch (status) {
    case 'waiting': return { text: 'Waiting...', cls: 'aia-synth__badge--waiting' };
    case 'streaming': return { text: 'Synthesizing', cls: 'aia-synth__badge--streaming' };
    case 'complete': return { text: 'Complete', cls: 'aia-synth__badge--complete' };
    case 'error': return { text: 'Error', cls: 'aia-synth__badge--error' };
    default: return { text: status, cls: '' };
  }
}
</script>

<template>
  <div class="aia-synth" :class="{ 'aia-synth--streaming': isStreaming }">
    <div class="aia-synth__header">
      <!-- Sparkle icon. Back-migrated from Agented. -->
      <span v-if="sparkleIcon" class="aia-synth__sparkle" aria-hidden="true">&#x2728;</span>
      <span class="aia-synth__label">Compound Synthesis</span>
      <span v-if="state.primaryBackend" class="aia-synth__via">via {{ state.primaryBackend }}</span>
      <span class="aia-synth__badge" :class="statusBadge(state.status).cls">
        {{ statusBadge(state.status).text }}
      </span>
    </div>
    <div v-if="state.backendsCollected.length" class="aia-synth__sources">
      Sources: {{ state.backendsCollected.join(', ') }}
    </div>
    <!-- Pulsing placeholder while empty + streaming/waiting. Back-migrated from Agented. -->
    <div v-if="showPlaceholder" class="aia-synth__placeholder">
      {{ placeholderText }}
    </div>
    <div v-else class="aia-synth__content" v-html="html" />
    <div v-if="state.error" class="aia-synth__error">{{ state.error }}</div>
  </div>
</template>

<style scoped>
.aia-synth {
  border: 1px solid var(--aia-border, #27272a); border-radius: var(--aia-radius, 8px);
  background: var(--aia-bg-elevated, #141414); overflow: hidden; margin: var(--aia-space-2, 8px) 0;
  border-left: 3px solid var(--aia-primary, #7c3aed);
}
.aia-synth__header {
  display: flex; align-items: center; gap: var(--aia-space-2, 8px);
  padding: var(--aia-space-2, 8px) var(--aia-space-3, 12px);
  background: rgba(124,58,237,0.08);
}
.aia-synth__label { font-weight: 700; font-size: var(--aia-text-sm, 14px); color: var(--aia-primary-hover, #8b5cf6); }
.aia-synth__via { font-size: var(--aia-text-xs, 12px); color: var(--aia-fg-subtle, #71717a); }
.aia-synth__badge {
  font-size: var(--aia-text-xs, 12px); padding: 1px 8px;
  border-radius: var(--aia-radius-sm, 4px); margin-left: auto; font-weight: 500;
}
.aia-synth__badge--waiting { background: rgba(161,161,170,0.15); color: #a1a1aa; }
.aia-synth__badge--streaming { background: rgba(96,165,250,0.15); color: #60a5fa; }
.aia-synth__badge--complete { background: rgba(16,185,129,0.15); color: #34d399; }
.aia-synth__badge--error { background: rgba(239,68,68,0.15); color: #ef4444; }
.aia-synth__sources {
  padding: var(--aia-space-1, 4px) var(--aia-space-3, 12px);
  font-size: var(--aia-text-xs, 12px); color: var(--aia-fg-subtle, #71717a);
}
.aia-synth__content {
  padding: var(--aia-space-3, 12px); font-size: var(--aia-text-sm, 14px);
  line-height: 1.6; color: var(--aia-fg, #fafafa);
}
.aia-synth__content :deep(pre) { background: var(--aia-bg, #0a0a0a); border-radius: var(--aia-radius, 8px); padding: 0.75rem; overflow-x: auto; margin: 0.5rem 0; font-size: 0.8rem; }
.aia-synth__content :deep(code) { font-family: var(--aia-font-mono, monospace); }
.aia-synth__content :deep(p) { margin: 0.25rem 0; }
.aia-synth__content :deep(ul),
.aia-synth__content :deep(ol) { padding-inline-start: 1.5rem; margin: 0.25rem 0; }
.aia-synth__content :deep(li) { margin: 0.125rem 0; }
.aia-synth__content :deep(li > ul),
.aia-synth__content :deep(li > ol) { margin: 0.125rem 0; }
.aia-synth__content :deep(h1),
.aia-synth__content :deep(h2),
.aia-synth__content :deep(h3),
.aia-synth__content :deep(h4),
.aia-synth__content :deep(h5),
.aia-synth__content :deep(h6) { font-weight: 700; line-height: 1.25; margin: 0.75rem 0 0.35rem; color: var(--aia-fg, #fafafa); }
.aia-synth__content :deep(h1) { font-size: 1.35rem; }
.aia-synth__content :deep(h2) { font-size: 1.15rem; }
.aia-synth__content :deep(h3) { font-size: 1.0rem; }
.aia-synth__content :deep(h4) { font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--aia-fg-muted, #a1a1aa); }
.aia-synth__content :deep(h5),
.aia-synth__content :deep(h6) { font-size: 0.9rem; color: var(--aia-fg-muted, #a1a1aa); }
.aia-synth__content :deep(blockquote) { border-left: 3px solid var(--aia-border-strong, #3f3f46); padding: 0.15rem 0.6rem; margin: 0.4rem 0; color: var(--aia-fg-muted, #a1a1aa); }
.aia-synth__content :deep(table) { border-collapse: collapse; margin: 0.5rem 0; font-size: 0.85rem; }
.aia-synth__content :deep(th),
.aia-synth__content :deep(td) { border: 1px solid var(--aia-border, #27272a); padding: 0.3rem 0.55rem; text-align: left; }
.aia-synth__content :deep(th) { background: var(--aia-bg-hover, #1f1f1f); font-weight: 600; }
.aia-synth__content :deep(hr) { border: 0; border-top: 1px solid var(--aia-border, #27272a); margin: 0.6rem 0; }
.aia-synth__content :deep(a) { color: var(--aia-link, #60a5fa); text-decoration: underline; }
.aia-synth__content :deep(a:hover) { text-decoration: none; }
.aia-synth__content :deep(strong) { color: var(--aia-fg, #fafafa); }
.aia-synth__content :deep(em) { font-style: italic; }
.aia-synth--streaming .aia-synth__content::after { content: '\25AE'; animation: aia-synth-blink 1s step-end infinite; }
.aia-synth__error { padding: var(--aia-space-2, 8px) var(--aia-space-3, 12px); font-size: var(--aia-text-xs, 12px); color: var(--aia-danger, #ef4444); }
@keyframes aia-synth-blink { 50% { opacity: 0; } }
/* Sparkle glyph + pulsing placeholder. Back-migrated from Agented. */
.aia-synth__sparkle { font-size: var(--aia-text-sm, 14px); }
.aia-synth__placeholder {
  padding: var(--aia-space-3, 12px); font-size: var(--aia-text-sm, 14px);
  font-style: italic; color: var(--aia-fg-subtle, #71717a);
  animation: aia-synth-pulse 1.5s ease-in-out infinite;
}
@keyframes aia-synth-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
</style>
