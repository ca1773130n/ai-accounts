<script setup lang="ts">
import { ref } from 'vue'

interface MessageLike {
  role: string
  content: string
  created_at?: string
}

interface Props {
  content: string
  allMessages?: MessageLike[]
}

defineProps<Props>()

const copyState = ref<'idle' | 'success' | 'error'>('idle')

async function copyToClipboard(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    copyState.value = 'success'
  } catch {
    copyState.value = 'error'
  }
  setTimeout(() => { copyState.value = 'idle' }, 1000)
}

function formatConversation(msgs: MessageLike[]): string {
  return msgs.map(m => `[${m.role}] ${m.created_at ?? ''}\n${m.content}`).join('\n\n---\n\n')
}

function exportConversation(msgs: MessageLike[]) {
  const text = formatConversation(msgs)
  const blob = new Blob([text], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `conversation-${new Date().toISOString().slice(0, 19)}.txt`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="message-actions">
    <button class="action-btn action-copy" title="Copy message" @click="copyToClipboard(content)">
      <span v-if="copyState === 'idle'">Copy</span>
      <span v-else-if="copyState === 'success'">Copied</span>
      <span v-else>Failed</span>
    </button>
    <button
      v-if="allMessages"
      class="action-btn action-copy-all"
      title="Copy conversation"
      @click="copyToClipboard(formatConversation(allMessages!))"
    >
      Copy All
    </button>
    <button
      v-if="allMessages"
      class="action-btn action-export"
      title="Export conversation"
      @click="exportConversation(allMessages!)"
    >
      Export
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
}
.action-btn:hover {
  background: var(--aia-bg-hover, #252540);
  color: var(--aia-text, #e0e0e0);
}
</style>
