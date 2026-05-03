<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import type { ProcessGroupType } from '@ai-accounts/ts-core'

interface Props {
  id: string
  type: ProcessGroupType
  label: string
  timestamp?: string
  isExpanded?: boolean
  /**
   * When > 0, schedule an auto-collapse timer that fires after the
   * given milliseconds. The timer is cancelled on `mouseenter` and
   * rescheduled on `mouseleave`. When the timer fires while expanded,
   * the component emits `toggle` so the parent can flip
   * `isExpanded` to false. Default `0` = disabled.
   * Back-migrated from Agented.
   */
  autoCollapseMs?: number
  /**
   * When true, render an inline SVG icon (wrench / brain / terminal)
   * inside the type badge in addition to the text label. Default
   * `false` preserves the upstream text-only badge.
   * Back-migrated from Agented.
   */
  iconBadges?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isExpanded: true,
  autoCollapseMs: 0,
  iconBadges: false,
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

/** Robust time formatter — silently swallow Invalid Date.
 *  Back-migrated from Agented. */
function formatTime(ts: string | undefined): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString()
}

// --- Auto-collapse timer (opt-in via autoCollapseMs > 0) ---
const isHovered = ref(false)
let collapseTimer: ReturnType<typeof setTimeout> | null = null

function cancelCollapse() {
  if (collapseTimer !== null) {
    clearTimeout(collapseTimer)
    collapseTimer = null
  }
}

function scheduleCollapse() {
  cancelCollapse()
  if (props.autoCollapseMs > 0 && !isHovered.value && props.isExpanded) {
    collapseTimer = setTimeout(() => {
      // Only toggle if still expanded — avoid re-entrant emits.
      if (props.isExpanded) emit('toggle')
    }, props.autoCollapseMs)
  }
}

function onMouseEnter() {
  isHovered.value = true
  cancelCollapse()
}

function onMouseLeave() {
  isHovered.value = false
  scheduleCollapse()
}

onMounted(() => {
  scheduleCollapse()
})

onUnmounted(() => {
  cancelCollapse()
})

// Re-arm when caller flips isExpanded back to true (e.g. user clicks
// to re-expand after the parent collapsed it). Without this, the
// auto-collapse would only fire once.
watch(
  () => props.isExpanded,
  (expanded) => {
    if (expanded) scheduleCollapse()
    else cancelCollapse()
  },
)
</script>

<template>
  <div
    class="process-group"
    :class="[`process-group--${type}`]"
    @mouseenter="onMouseEnter"
    @mouseleave="onMouseLeave"
  >
    <div class="process-group-header" @click="emit('toggle')">
      <span
        class="process-group-badge"
        :class="[`process-group-badge--${type}`, { 'process-group-badge--with-icon': iconBadges }]"
        :style="{ background: badgeColor[type] }"
      >
        <!-- Optional SVG icons. Back-migrated from Agented. -->
        <svg
          v-if="iconBadges && type === 'tool_call'"
          class="process-group-badge-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/>
        </svg>
        <svg
          v-else-if="iconBadges && type === 'reasoning'"
          class="process-group-badge-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="M12 2a8 8 0 018 8c0 3-2 5.5-4 7l-1 4H9l-1-4c-2-1.5-4-4-4-7a8 8 0 018-8z"/>
          <path d="M9 21h6M10 17h4"/>
        </svg>
        <svg
          v-else-if="iconBadges && type === 'code_execution'"
          class="process-group-badge-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <polyline points="4 17 10 11 4 5"/>
          <line x1="12" y1="19" x2="20" y2="19"/>
        </svg>
        {{ badgeLabel[type] }}
      </span>
      <span class="process-group-label">{{ label }}</span>
      <span v-if="timestamp && formatTime(timestamp)" class="process-group-time">
        {{ formatTime(timestamp) }}
      </span>
      <span class="process-group-chevron">{{ isExpanded ? '▼' : '▶' }}</span>
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
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.process-group-badge-icon {
  width: 12px;
  height: 12px;
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
