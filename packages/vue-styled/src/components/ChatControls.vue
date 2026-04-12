<script setup lang="ts">
import type { ChatMode, BackendOption } from '@ai-accounts/ts-core';
import { computed } from 'vue';

const props = defineProps<{
  chatMode: ChatMode;
  selectedBackend: string | null;
  selectedModel: string | null;
  backends: BackendOption[];
}>();

const emit = defineEmits<{
  'update:chatMode': [mode: ChatMode];
  'update:selectedBackend': [kind: string | null];
  'update:selectedModel': [model: string | null];
}>();

const modes: { value: ChatMode; label: string }[] = [
  { value: 'single', label: 'Single' },
  { value: 'all', label: 'All' },
  { value: 'compound', label: 'Compound' },
];

const isAutoMode = computed(() => !props.selectedBackend);

const activeBackend = computed(() =>
  props.backends.find((b) => b.kind === props.selectedBackend),
);

const accounts = computed(() => activeBackend.value?.accounts ?? []);
const models = computed(() => activeBackend.value?.models ?? []);
</script>

<template>
  <div class="aia-controls">
    <!-- Backend -->
    <div class="aia-controls__group">
      <label class="aia-controls__label">Backend</label>
      <select
        class="aia-controls__select"
        :value="selectedBackend ?? ''"
        @change="emit('update:selectedBackend', ($event.target as HTMLSelectElement).value || null)"
      >
        <option value="">Auto</option>
        <option v-for="b in backends" :key="b.kind" :value="b.kind">{{ b.displayName }}</option>
      </select>
    </div>

    <!-- Account -->
    <div class="aia-controls__group">
      <label class="aia-controls__label">Account</label>
      <select class="aia-controls__select" :disabled="isAutoMode">
        <option value="">{{ isAutoMode ? '--' : 'Default' }}</option>
        <option v-for="acc in accounts" :key="acc" :value="acc">{{ acc }}</option>
      </select>
    </div>

    <!-- Model -->
    <div class="aia-controls__group">
      <label class="aia-controls__label">Model</label>
      <select
        class="aia-controls__select"
        :disabled="isAutoMode"
        :value="selectedModel ?? ''"
        @change="emit('update:selectedModel', ($event.target as HTMLSelectElement).value || null)"
      >
        <option value="">{{ isAutoMode ? '--' : 'Default' }}</option>
        <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
      </select>
    </div>

    <!-- Mode -->
    <div class="aia-controls__group aia-controls__group--mode">
      <label class="aia-controls__label">Mode</label>
      <div class="aia-controls__modes">
        <button
          v-for="m in modes" :key="m.value"
          class="aia-controls__mode-btn"
          :class="{ 'aia-controls__mode-btn--active': chatMode === m.value }"
          @click="emit('update:chatMode', m.value)"
        >{{ m.label }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aia-controls {
  display: flex; flex-wrap: wrap; gap: var(--aia-space-3, 12px);
  padding: var(--aia-space-3, 12px); border-bottom: 1px solid var(--aia-border, #27272a);
  background: var(--aia-bg-elevated, #141414);
}
.aia-controls__group { display: flex; flex-direction: column; gap: var(--aia-space-1, 4px); min-width: 120px; }
.aia-controls__group--mode { margin-left: auto; }
.aia-controls__label { font-size: var(--aia-text-xs, 12px); font-weight: 600; color: var(--aia-fg-muted, #a1a1aa); text-transform: uppercase; letter-spacing: 0.04em; }
.aia-controls__select {
  appearance: none; background: var(--aia-bg, #0a0a0a); color: var(--aia-fg, #fafafa);
  border: 1px solid var(--aia-border, #27272a); border-radius: var(--aia-radius-sm, 4px);
  padding: var(--aia-space-1, 4px) var(--aia-space-2, 8px); font-size: var(--aia-text-sm, 14px);
  cursor: pointer; transition: border-color var(--aia-transition, 150ms ease-out);
}
.aia-controls__select:hover:not(:disabled) { border-color: var(--aia-border-hover, #3f3f46); }
.aia-controls__select:disabled { opacity: 0.4; cursor: not-allowed; }
.aia-controls__modes { display: flex; gap: 2px; background: var(--aia-bg, #0a0a0a); border-radius: var(--aia-radius-sm, 4px); padding: 2px; }
.aia-controls__mode-btn {
  padding: var(--aia-space-1, 4px) var(--aia-space-2, 8px); border: none; border-radius: 3px;
  background: transparent; color: var(--aia-fg-muted, #a1a1aa); font-size: var(--aia-text-xs, 12px);
  font-weight: 500; cursor: pointer; transition: all var(--aia-transition, 150ms ease-out);
}
.aia-controls__mode-btn:hover { color: var(--aia-fg, #fafafa); }
.aia-controls__mode-btn--active { background: var(--aia-primary, #7c3aed); color: var(--aia-primary-fg, #fff); }
</style>
