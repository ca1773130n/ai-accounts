<script setup lang="ts">
import { ref } from 'vue'

/**
 * Generic message shape consumed by MessageActions. Both `created_at`
 * and `timestamp` are honored — upstream callers historically use
 * `created_at`; Agented callers use `timestamp`. Either (or neither)
 * may be present.
 */
interface MessageLike {
  role: string
  content: string
  created_at?: string
  /** Alternative timestamp field. Back-migrated from Agented. */
  timestamp?: string
}

interface Props {
  content: string
  allMessages?: MessageLike[]
  /**
   * When true, render the action buttons as inline SVG icons with the
   * copy state communicated visually (clipboard / checkmark / X)
   * instead of as text labels. Default `false` preserves the upstream
   * "Copy"/"Copied"/"Failed" text-only buttons.
   * Back-migrated from Agented.
   */
  iconButtons?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  iconButtons: false,
})

const copyState = ref<'idle' | 'success' | 'error'>('idle')

function setCopyFeedback(state: 'success' | 'error') {
  copyState.value = state
  setTimeout(() => {
    copyState.value = 'idle'
  }, 1000)
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      setCopyFeedback('success')
      return true
    }
    // execCommand fallback for non-secure contexts. Back-migrated from Agented.
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    setCopyFeedback(ok ? 'success' : 'error')
    return ok
  } catch {
    setCopyFeedback('error')
    return false
  }
}

function copyMessage() {
  copyToClipboard(props.content)
}

function pickTimestamp(m: MessageLike): string {
  return m.created_at ?? m.timestamp ?? ''
}

function formatConversation(msgs: MessageLike[]): string {
  return msgs
    .map((m) => `[${m.role}] ${pickTimestamp(m)}\n${m.content}`)
    .join('\n\n---\n\n')
}

function copyAllConversation() {
  if (!props.allMessages || props.allMessages.length === 0) return
  copyToClipboard(formatConversation(props.allMessages))
}

function exportConversation() {
  if (!props.allMessages || props.allMessages.length === 0) return
  const text = formatConversation(props.allMessages)
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `conversation-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.txt`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="message-actions">
    <button
      class="action-btn action-copy"
      :title="
        copyState === 'success'
          ? 'Copied!'
          : copyState === 'error'
            ? 'Copy failed'
            : 'Copy message'
      "
      @click.stop="copyMessage"
    >
      <template v-if="iconButtons">
        <!-- Checkmark / X / Clipboard icons. Back-migrated from Agented. -->
        <svg
          v-if="copyState === 'success'"
          class="action-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="M20 6L9 17l-5-5"/>
        </svg>
        <svg
          v-else-if="copyState === 'error'"
          class="action-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
        <svg
          v-else
          class="action-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
        </svg>
      </template>
      <template v-else>
        <span v-if="copyState === 'idle'">Copy</span>
        <span v-else-if="copyState === 'success'">Copied</span>
        <span v-else>Failed</span>
      </template>
    </button>
    <button
      v-if="allMessages"
      class="action-btn action-copy-all"
      title="Copy conversation"
      @click.stop="copyAllConversation"
    >
      <template v-if="iconButtons">
        <svg
          class="action-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
          <line x1="14" y1="14" x2="18" y2="14"/>
          <line x1="14" y1="17" x2="18" y2="17"/>
        </svg>
      </template>
      <template v-else>Copy All</template>
    </button>
    <button
      v-if="allMessages"
      class="action-btn action-export"
      title="Export conversation"
      @click.stop="exportConversation"
    >
      <template v-if="iconButtons">
        <svg
          class="action-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
      </template>
      <template v-else>Export</template>
    </button>
  </div>
</template>

<style scoped>
.message-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s;
  position: absolute;
  top: 4px;
  right: 4px;
}
.action-btn {
  background: var(--aia-bg-secondary, #1a1a2e);
  border: 1px solid var(--aia-border, #333);
  border-radius: 4px;
  padding: 2px 6px;
  cursor: pointer;
  font-size: 11px;
  color: var(--aia-text-muted, #888);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.action-btn:hover {
  background: var(--aia-bg-hover, #252540);
  color: var(--aia-text, #e0e0e0);
}
.action-icon {
  width: 14px;
  height: 14px;
}
</style>
