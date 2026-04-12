<script setup lang="ts">
import { computed } from 'vue';
import { marked } from 'marked';
import type { BackendResponseState } from '@ai-accounts/vue-headless';

const props = withDefaults(defineProps<{
  responses: Map<string, BackendResponseState>;
  collapsible?: boolean;
}>(), {
  collapsible: false,
});

const BACKEND_COLORS: Record<string, { bg: string; fg: string; label: string }> = {
  claude: { bg: 'rgba(139,92,246,0.15)', fg: '#a78bfa', label: 'Claude' },
  codex: { bg: 'rgba(16,185,129,0.15)', fg: '#34d399', label: 'Codex' },
  gemini: { bg: 'rgba(96,165,250,0.15)', fg: '#60a5fa', label: 'Gemini' },
  opencode: { bg: 'rgba(251,191,36,0.15)', fg: '#fbbf24', label: 'OpenCode' },
};

function backendMeta(kind: string) {
  return BACKEND_COLORS[kind] ?? { bg: 'rgba(161,161,170,0.15)', fg: '#a1a1aa', label: kind };
}

function statusBadge(status: BackendResponseState['status']) {
  switch (status) {
    case 'streaming': return { text: 'Streaming', cls: 'aia-resp__badge--streaming' };
    case 'complete': return { text: 'Done', cls: 'aia-resp__badge--complete' };
    case 'error': return { text: 'Error', cls: 'aia-resp__badge--error' };
    case 'timeout': return { text: 'Timeout', cls: 'aia-resp__badge--timeout' };
    default: return { text: status, cls: '' };
  }
}

const entries = computed(() => Array.from(props.responses.entries()));

function renderMarkdown(content: string): string {
  return marked.parse(content || '') as string;
}
</script>

<template>
  <div class="aia-responses">
    <div
      v-for="[key, resp] in entries" :key="key"
      class="aia-resp"
      :style="{ '--resp-bg': backendMeta(resp.backend).bg, '--resp-fg': backendMeta(resp.backend).fg }"
    >
      <details :open="!collapsible || undefined">
        <summary class="aia-resp__header">
          <span class="aia-resp__name" :style="{ color: backendMeta(resp.backend).fg }">
            {{ backendMeta(resp.backend).label }}
          </span>
          <span class="aia-resp__badge" :class="statusBadge(resp.status).cls">
            {{ statusBadge(resp.status).text }}
          </span>
        </summary>
        <div class="aia-resp__body" v-html="renderMarkdown(resp.content)" />
        <div v-if="resp.error" class="aia-resp__error">{{ resp.error }}</div>
      </details>
    </div>
  </div>
</template>

<style scoped>
.aia-responses { display: flex; flex-direction: column; gap: var(--aia-space-2, 8px); padding: var(--aia-space-2, 8px) 0; }
.aia-resp {
  border: 1px solid var(--aia-border, #27272a); border-radius: var(--aia-radius, 8px);
  background: var(--aia-bg-elevated, #141414); overflow: hidden;
}
.aia-resp__header {
  display: flex; align-items: center; gap: var(--aia-space-2, 8px);
  padding: var(--aia-space-2, 8px) var(--aia-space-3, 12px);
  background: var(--resp-bg); cursor: pointer; user-select: none;
  list-style: none;
}
.aia-resp__header::-webkit-details-marker { display: none; }
.aia-resp__name { font-weight: 600; font-size: var(--aia-text-sm, 14px); }
.aia-resp__badge {
  font-size: var(--aia-text-xs, 12px); padding: 1px 8px;
  border-radius: var(--aia-radius-sm, 4px); margin-left: auto; font-weight: 500;
}
.aia-resp__badge--streaming { background: rgba(96,165,250,0.15); color: #60a5fa; }
.aia-resp__badge--complete { background: rgba(16,185,129,0.15); color: #34d399; }
.aia-resp__badge--error { background: rgba(239,68,68,0.15); color: #ef4444; }
.aia-resp__badge--timeout { background: rgba(245,158,11,0.15); color: #f59e0b; }
.aia-resp__body {
  padding: var(--aia-space-3, 12px); font-size: var(--aia-text-sm, 14px);
  line-height: 1.6; color: var(--aia-fg, #fafafa);
}
.aia-resp__body :deep(pre) { background: var(--aia-bg, #0a0a0a); border-radius: var(--aia-radius, 8px); padding: 0.75rem; overflow-x: auto; margin: 0.5rem 0; font-size: 0.8rem; }
.aia-resp__body :deep(code) { font-family: var(--aia-font-mono, monospace); }
.aia-resp__body :deep(p) { margin: 0.25rem 0; }
.aia-resp__error { padding: var(--aia-space-2, 8px) var(--aia-space-3, 12px); font-size: var(--aia-text-xs, 12px); color: var(--aia-danger, #ef4444); }
</style>
