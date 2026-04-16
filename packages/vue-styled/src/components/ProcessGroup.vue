<script setup lang="ts">
import type { ProcessGroupType } from '@ai-accounts/ts-core'

interface Props {
  id: string
  type: ProcessGroupType
  label: string
  timestamp?: string
  isExpanded?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isExpanded: true,
})

const emit = defineEmits<{
  toggle: []
}>()

const badgeLabel: Record<ProcessGroupType, string> = {
  tool_call: 'Tool',
  reasoning: 'Thinking',
  code_execution: 'Code',
}

const badgeColor: Record<ProcessGroupType, string> = {
  tool_call: 'var(--aia-cyan, #22d3ee)',
  reasoning: 'var(--aia-violet, #a78bfa)',
  code_execution: 'var(--aia-amber, #fbbf24)',
}
</script>

<template>
  <div class="process-group" :class="[`process-group--${type}`]">
    <div class="process-group-header" @click="emit('toggle')">
      <span class="process-group-badge" :style="{ background: badgeColor[type] }">
        {{ badgeLabel[type] }}
      </span>
      <span class="process-group-label">{{ label }}</span>
      <span v-if="timestamp" class="process-group-time">
        {{ new Date(timestamp).toLocaleTimeString() }}
      </span>
      <span class="process-group-chevron">{{ isExpanded ? '\u25BC' : '\u25B6' }}</span>
    </div>
    <div v-if="isExpanded" class="process-group-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.process-group {
  border: 1px solid var(--aia-border, #333);
  border-radius: 8px;
  margin: 8px 0;
  overflow: hidden;
}
.process-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  background: var(--aia-bg-secondary, #1a1a2e);
  user-select: none;
}
.process-group-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  color: #000;
}
.process-group-label {
  font-family: monospace;
  font-size: 13px;
  color: var(--aia-text, #e0e0e0);
  flex: 1;
}
.process-group-time {
  font-size: 11px;
  color: var(--aia-text-muted, #888);
}
.process-group-chevron {
  font-size: 10px;
  color: var(--aia-text-muted, #888);
}
.process-group-body {
  padding: 8px 12px;
  max-height: 300px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 13px;
  white-space: pre-wrap;
  color: var(--aia-text, #e0e0e0);
  border-top: 1px solid var(--aia-border, #333);
}
</style>
