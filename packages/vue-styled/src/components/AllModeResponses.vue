<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { marked } from 'marked';
import type { BackendResponseState } from '@ai-accounts/vue-headless';

interface Props {
  responses: Map<string, BackendResponseState>;
  collapsible?: boolean;
  /**
   * When true, render a single global toggle header
   * ("N/total backends responded" + chevron) above the response cards.
   * The cards are hidden until the user clicks the header. This is
   * the Agented "compound mode" collapse: one summary, many cards.
   * Default `false` preserves the upstream per-card `<details>` UX.
   * Back-migrated from Agented.
   */
  summaryHeader?: boolean;
  /**
   * Optional placeholder text rendered in a streaming card whose
   * `content` is still empty. When `null` (default) the body is
   * suppressed exactly as today. When set (typically
   * "Waiting for response...") the body is rendered with the
   * placeholder string in italics.
   * Back-migrated from Agented.
   */
  waitingPlaceholder?: string | null;
}

const props = withDefaults(defineProps<Props>(), {
  collapsible: false,
  summaryHeader: false,
  waitingPlaceholder: null,
});

const BACKEND_COLORS: Record<string, { bg: string; fg: string; label: string }> = {
  claude: { bg: 'rgba(139,92,246,0.15)', fg: '#a78bfa', label: 'Claude' },
  codex: { bg: 'rgba(16,185,129,0.15)', fg: '#34d399', label: 'Codex' },
  gemini: { bg: 'rgba(96,165,250,0.15)', fg: '#60a5fa', label: 'Gemini' },
  opencode: { bg: 'rgba(251,191,36,0.15)', fg: '#fbbf24', label: 'OpenCode' },
};

function backendMeta(kind: string | undefined | null) {
  if (!kind) return { bg: 'rgba(161,161,170,0.15)', fg: '#a1a1aa', label: 'Backend' };
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

/** Map raw backend_error strings to a friendlier title + actionable hint.
 *  Keeps the raw message visible as the detail line so power users / logs
 *  still get the underlying cause. */
function explainError(raw: string): { title: string; hint: string | null } {
  const msg = raw || '';
  if (/^no models available/i.test(msg)) {
    return {
      title: 'No models available',
      hint: 'CLIProxyAPI advertises zero models for this backend. Make sure cliproxyapi is running and this backend’s account is registered.',
    };
  }
  if (/^could not enumerate models/i.test(msg)) {
    return {
      title: 'Could not list models',
      hint: 'Failed to fetch the model list for this backend.',
    };
  }
  if (/^no account available/i.test(msg)) {
    return {
      title: 'No account available',
      hint: 'No ready account is registered for this backend kind.',
    };
  }
  // Specific upstream rejection: model not supported on this auth method.
  // Renders as a soft notice instead of a scary "Upstream proxy error" —
  // this is a known constraint, not a bug. Common case: ChatGPT-auth Codex
  // can't serve gpt-5.1 / gpt-5.1-codex-mini without an API key.
  const notSupported = msg.match(/'([^']+)' (?:model )?is not supported when using (\w+) with a ([^']+?) account/i);
  if (notSupported) {
    return {
      title: `${notSupported[1]} not available`,
      hint: `Your ${notSupported[2]} account is authenticated via ${notSupported[3]}, which doesn't expose this model. Switch to an API-key login or pick a different model.`,
    };
  }
  if (/^Proxy error/i.test(msg)) {
    return { title: 'Upstream proxy error', hint: null };
  }
  if (/timed?\s*out/i.test(msg)) {
    return { title: 'Backend timed out', hint: null };
  }
  return { title: 'Backend error', hint: null };
}

const entries = computed(() => Array.from(props.responses.entries()));

function renderMarkdown(content: string): string {
  return marked.parse(content || '') as string;
}

// --- Summary header collapse state. Back-migrated from Agented. ---
const summaryExpanded = ref(false);

/** Summary line: "N/total backends responded" or "total backend responses". */
const collapsedSummary = computed(() => {
  const total = entries.value.length;
  const complete = entries.value.filter(([, r]) => r.status === 'complete').length;
  const inFlight = total - complete;
  if (inFlight > 0) return `${complete}/${total} backends responded`;
  return `${total} backend responses`;
});

// If summaryHeader is turned off after being on, reset the expand state
// so the next toggle starts collapsed.
watch(
  () => props.summaryHeader,
  (val) => {
    if (!val) summaryExpanded.value = false;
  },
);

/** True when we should render the markdown body for this card. */
function bodyShown(resp: BackendResponseState): boolean {
  // Suppress the body for non-success states with no content (existing).
  if ((resp.status === 'error' || resp.status === 'timeout') && !resp.content) return false;
  // With waitingPlaceholder set, an empty streaming card now shows the
  // placeholder text instead of an empty box. Back-migrated from Agented.
  if (props.waitingPlaceholder && resp.status === 'streaming' && !resp.content) return true;
  return true;
}

/** Render content if present, else fall back to the waitingPlaceholder
 *  (italicized) — only used when bodyShown(resp) is true. */
function bodyHtml(resp: BackendResponseState): string {
  if (!resp.content && props.waitingPlaceholder && resp.status === 'streaming') {
    return `<em class="aia-resp__waiting">${props.waitingPlaceholder}</em>`;
  }
  return renderMarkdown(resp.content);
}
</script>

<template>
  <div class="aia-responses">
    <!-- Optional global summary toggle. Back-migrated from Agented. -->
    <button
      v-if="summaryHeader && entries.length > 0"
      class="aia-responses__summary"
      @click="summaryExpanded = !summaryExpanded"
    >
      <svg
        :class="['aia-responses__summary-chevron', { 'is-open': summaryExpanded }]"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        width="14" height="14" aria-hidden="true"
      >
        <polyline points="9 18 15 12 9 6" />
      </svg>
      <span class="aia-responses__summary-label">Individual Responses</span>
      <span class="aia-responses__summary-count">{{ collapsedSummary }}</span>
    </button>
    <template v-if="!summaryHeader || summaryExpanded">
    <div
      v-for="[key, resp] in entries" :key="key"
      class="aia-resp"
      :class="{ 'aia-resp--error': resp.status === 'error', 'aia-resp--timeout': resp.status === 'timeout' }"
      :style="{ '--resp-bg': backendMeta(resp.backendKind).bg, '--resp-fg': backendMeta(resp.backendKind).fg }"
    >
      <details :open="!collapsible || undefined">
        <summary class="aia-resp__header">
          <span class="aia-resp__name" :style="{ color: backendMeta(resp.backendKind).fg }">
            {{ backendMeta(resp.backendKind).label }}
          </span>
          <span v-if="resp.accountLabel" class="aia-resp__account">{{ resp.accountLabel }}</span>
          <span class="aia-resp__badge" :class="statusBadge(resp.status).cls">
            {{ statusBadge(resp.status).text }}
          </span>
        </summary>
        <div v-if="bodyShown(resp)" class="aia-resp__body" v-html="bodyHtml(resp)" />
        <div v-if="resp.error" class="aia-resp__error" role="alert">
          <!-- Status icon: triangle for error, clock for timeout. -->
          <svg
            v-if="resp.status === 'timeout'"
            class="aia-resp__error-icon"
            viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            width="16" height="16" aria-hidden="true"
          >
            <circle cx="12" cy="12" r="9" />
            <polyline points="12 7 12 12 15 14" />
          </svg>
          <svg
            v-else
            class="aia-resp__error-icon"
            viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            width="16" height="16" aria-hidden="true"
          >
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <div class="aia-resp__error-text">
            <strong class="aia-resp__error-title">{{ explainError(resp.error).title }}</strong>
            <p v-if="explainError(resp.error).hint" class="aia-resp__error-hint">
              {{ explainError(resp.error).hint }}
            </p>
            <code class="aia-resp__error-detail">{{ resp.error }}</code>
          </div>
        </div>
      </details>
    </div>
    </template>
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
.aia-resp__account {
  font-size: var(--aia-text-xs, 12px);
  color: var(--aia-fg-muted, #a1a1aa);
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
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
.aia-resp__body :deep(ul),
.aia-resp__body :deep(ol) { padding-inline-start: 1.5rem; margin: 0.25rem 0; }
.aia-resp__body :deep(li) { margin: 0.125rem 0; }
.aia-resp__body :deep(li > ul),
.aia-resp__body :deep(li > ol) { margin: 0.125rem 0; }
.aia-resp--error {
  border-color: rgba(239, 68, 68, 0.4);
  box-shadow: inset 3px 0 0 var(--aia-danger, #ef4444);
}
.aia-resp--timeout {
  border-color: rgba(245, 158, 11, 0.4);
  box-shadow: inset 3px 0 0 var(--aia-warning, #f59e0b);
}
.aia-resp__error {
  display: flex;
  gap: var(--aia-space-2, 8px);
  align-items: flex-start;
  padding: var(--aia-space-3, 12px);
  font-size: var(--aia-text-sm, 14px);
  background: rgba(239, 68, 68, 0.04);
  border-top: 1px solid rgba(239, 68, 68, 0.15);
}
.aia-resp--timeout .aia-resp__error {
  background: rgba(245, 158, 11, 0.05);
  border-top-color: rgba(245, 158, 11, 0.18);
}
.aia-resp__error-icon {
  color: var(--aia-danger, #ef4444);
  flex-shrink: 0;
  margin-top: 2px;
}
.aia-resp--timeout .aia-resp__error-icon { color: var(--aia-warning, #f59e0b); }
.aia-resp__error-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
.aia-resp__error-title {
  color: var(--aia-fg, #fafafa);
  font-weight: 600;
  font-size: var(--aia-text-sm, 14px);
  line-height: 1.3;
}
.aia-resp__error-hint {
  margin: 0;
  color: var(--aia-fg-muted, #a1a1aa);
  font-size: var(--aia-text-xs, 12px);
  line-height: 1.5;
}
.aia-resp__error-detail {
  font-family: var(--aia-font-mono, monospace);
  font-size: 0.72rem;
  color: var(--aia-fg-subtle, #71717a);
  background: var(--aia-bg, #0a0a0a);
  padding: 4px 8px;
  border-radius: var(--aia-radius-sm, 4px);
  border: 1px solid var(--aia-border, #27272a);
  word-break: break-word;
  white-space: pre-wrap;
  max-height: 6em;
  overflow-y: auto;
}
/* Global summary toggle. Back-migrated from Agented. */
.aia-responses__summary {
  display: flex;
  align-items: center;
  gap: var(--aia-space-2, 8px);
  width: 100%;
  padding: 10px 14px;
  background: var(--aia-bg-elevated, #141414);
  border: 1px solid var(--aia-border, #27272a);
  border-radius: var(--aia-radius, 8px);
  color: var(--aia-fg-muted, #a1a1aa);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--aia-text-sm, 13px);
  transition: background 0.15s;
}
.aia-responses__summary:hover { background: rgba(255, 255, 255, 0.04); }
.aia-responses__summary-chevron {
  flex-shrink: 0;
  transition: transform 0.2s;
}
.aia-responses__summary-chevron.is-open { transform: rotate(90deg); }
.aia-responses__summary-label {
  font-weight: 600;
  color: var(--aia-fg, #fafafa);
}
.aia-responses__summary-count {
  font-size: var(--aia-text-xs, 12px);
  color: var(--aia-fg-subtle, #71717a);
}
.aia-resp__body :deep(.aia-resp__waiting) {
  color: var(--aia-fg-subtle, #71717a);
  font-style: italic;
}
</style>
