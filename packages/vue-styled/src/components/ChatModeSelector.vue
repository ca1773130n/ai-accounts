<script setup lang="ts">
import type { ChatMode } from '@ai-accounts/ts-core'

/**
 * Standalone chat-mode segmented selector. A lighter alternative to
 * `ChatControls` for callers that only need the Single / All /
 * Compound toggle without the backend / account / model selects.
 *
 * Two-way bindable via `v-model:mode`. The list of modes is fixed
 * (Single / All / Compound) and matches the canonical
 * `ChatMode` union from `@ai-accounts/ts-core`.
 *
 * Back-migrated from Agented (`b2ee00d~1`, restored in Agented v0.5.5).
 */

defineProps<{ mode: ChatMode }>()
const emit = defineEmits<{
  (e: 'update:mode', value: ChatMode): void
}>()

const modes: Array<{ value: ChatMode; label: string; description: string }> = [
  { value: 'single', label: 'Single', description: 'Send to one backend' },
  { value: 'all', label: 'All', description: 'Send to all backends simultaneously' },
  { value: 'compound', label: 'Compound', description: 'All backends + AI synthesis' },
]
</script>

<template>
  <div class="aia-chat-mode-selector" role="radiogroup" aria-label="Chat mode">
    <button
      v-for="m in modes"
      :key="m.value"
      type="button"
      role="radio"
      :aria-checked="mode === m.value"
      :class="[
        'aia-chat-mode-selector__btn',
        { 'aia-chat-mode-selector__btn--active': mode === m.value },
      ]"
      :title="m.description"
      @click="emit('update:mode', m.value)"
    >
      {{ m.label }}
    </button>
  </div>
</template>

<style scoped>
.aia-chat-mode-selector {
  display: inline-flex;
  border: 1px solid var(--aia-border, #27272a);
  border-radius: var(--aia-radius, 6px);
  overflow: hidden;
}
.aia-chat-mode-selector__btn {
  padding: 4px 12px;
  font-size: var(--aia-text-xs, 12px);
  font-weight: 500;
  font-family: inherit;
  background: var(--aia-bg-elevated, #141414);
  color: var(--aia-fg-muted, #a1a1aa);
  border: none;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  border-right: 1px solid var(--aia-border, #27272a);
}
.aia-chat-mode-selector__btn:last-child {
  border-right: none;
}
.aia-chat-mode-selector__btn:hover:not(.aia-chat-mode-selector__btn--active) {
  background: var(--aia-bg-hover, #1f1f1f);
  color: var(--aia-fg, #fafafa);
}
.aia-chat-mode-selector__btn--active {
  background: var(--aia-primary, #7c3aed);
  color: #ffffff;
}
.aia-chat-mode-selector__btn:focus-visible {
  outline: 2px solid var(--aia-primary-hover, #8b5cf6);
  outline-offset: -2px;
}
</style>
