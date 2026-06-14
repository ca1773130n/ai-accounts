<script setup lang="ts">
import { computed } from 'vue';
import { marked } from 'marked';
import hljs from 'highlight.js';
import DOMPurify from 'dompurify';
import MessageActions from './MessageActions.vue';
import { backendDisplayName, modelDisplayName } from '../utils/assistantLabel';

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

const props = withDefaults(
  defineProps<{
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    /** Backend kind that produced this message (claude / codex / gemini /
     *  opencode). Drives the assistant author name shown in the header. */
    backend?: string | null;
    /** Model id that produced this message (e.g. `opus`, `gpt-5.1`).
     *  Rendered as a small pill beside the author name when present. */
    model?: string | null;
    timestamp?: string | null;
    streaming?: boolean;
    showActions?: boolean;
    allMessages?: MessageLike[];
    /** Custom SVG path(s) for the avatar icon. If omitted, a single
     *  letter (U / author-initial / S / T) is rendered. Back-migrated
     *  from Agented. */
    avatarPaths?: string[];
    /** Explicit display name for the bubble header for non-user roles.
     *  When omitted, the name is derived from `backend` (falling back to
     *  a generic "Assistant"). Back-migrated from Agented. */
    assistantName?: string;
    /** When true, suppress the 350ms fade-in animation (used for
     *  mass-rendering historical messages). Back-migrated from
     *  Agented. */
    skipTransition?: boolean;
  }>(),
  {
    streaming: false,
    showActions: false,
    skipTransition: false,
  },
);

// Sanitize the rendered markdown HTML before v-html. Without this,
// user-controlled prompts and model output that contain raw HTML
// (`<script>`, `<img onerror=…>`, `javascript:` href, etc.) get
// rendered as live DOM — an XSS vector for any host that feeds
// untrusted content to ChatBubble. DOMPurify's default config strips
// scripts, event handlers, and dangerous URL schemes while keeping
// the standard markdown-output subset (headings, lists, tables,
// code, formatting, safe links).
const html = computed(() =>
  DOMPurify.sanitize(marked.parse(props.content || '') as string) as string,
);
const timeStr = computed(() => {
  if (!props.timestamp) return '';
  // ``new Date('2026-05-10 12:34:56')`` (SQLite default format without
  // the ``T`` / ``Z``) silently returns an Invalid Date object on some
  // engines; ``toLocaleTimeString()`` then renders the literal string
  // ``"Invalid Date"`` without throwing, so a try/catch around the
  // conversion never fires. Guard with ``isNaN(getTime())`` so bad
  // timestamps render as empty instead of leaking into the bubble UI.
  const d = new Date(props.timestamp);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString();
});

function copyCode(e: Event) {
  const btn = (e.target as HTMLElement).closest('.aia-copy-btn');
  if (!btn) return;
  const pre = btn.closest('.aia-code-block')?.querySelector('code');
  if (pre) navigator.clipboard.writeText(pre.textContent || '');
}

// Author name shown in the header. Users are always "You"; assistants are
// labelled by who actually answered — an explicit `assistantName`, else the
// backend display name, else a generic "Assistant" (never "AI"). The
// backend-derived name applies only to assistant rows so a `backend` prop
// passed alongside a system/tool bubble can't mislabel it.
const authorName = computed(() => {
  if (props.role === 'user') return 'You';
  const explicit = props.assistantName?.trim();
  if (explicit) return explicit;
  if (props.role === 'assistant') {
    return backendDisplayName(props.backend) || 'Assistant';
  }
  return props.role;
});

// Single-letter avatar fallback (used when no `avatarPaths` SVG is given).
// Derives the assistant letter from the resolved author name so it tracks
// the backend (Claude -> "C") instead of a hardcoded "AI".
const avatarLetter = computed(() => {
  if (props.role === 'user') return 'U';
  if (props.role === 'tool') return 'T';
  if (props.role === 'system') return 'S';
  return (authorName.value.charAt(0) || 'A').toUpperCase();
});

// Model pill text; only assistant rows carry a model, so the pill never
// leaks onto user / system / tool bubbles. Empty string hides the pill.
const modelLabel = computed(() =>
  props.role === 'assistant' ? modelDisplayName(props.model) : '',
);
</script>

<template>
  <div
    class="aia-bubble"
    :class="[
      `aia-bubble--${role}`,
      { 'aia-bubble--streaming': streaming, 'aia-bubble--fade-in': !skipTransition },
    ]"
  >
    <div class="aia-bubble__avatar">
      <svg
        v-if="avatarPaths && avatarPaths.length > 0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <path v-for="(d, i) in avatarPaths" :key="i" :d="d" />
      </svg>
      <template v-else>
        {{ avatarLetter }}
      </template>
    </div>
    <div class="aia-bubble__body">
      <div class="aia-bubble__header">
        <span class="aia-bubble__role">{{ authorName }}</span>
        <span v-if="modelLabel" class="aia-bubble__model">{{ modelLabel }}</span>
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
.aia-bubble__model { font-size: 0.65rem; padding: 1px 6px; border-radius: var(--aia-radius-sm, 4px); background: var(--aia-bg-hover, #1f1f1f); color: var(--aia-fg-subtle, #71717a); }
.aia-bubble__time { font-size: 0.65rem; color: var(--aia-fg-subtle, #71717a); margin-left: auto; }
.aia-bubble__content { font-size: var(--aia-text-sm, 14px); line-height: 1.6; color: var(--aia-fg, #fafafa); }
.aia-bubble__content :deep(pre) { background: var(--aia-bg, #0a0a0a); border-radius: var(--aia-radius, 8px); padding: 0.75rem; overflow-x: auto; margin: 0.5rem 0; font-size: 0.8rem; }
.aia-bubble__content :deep(code) { font-family: var(--aia-font-mono, monospace); }
.aia-bubble__content :deep(p) { margin: 0.25rem 0; }
.aia-bubble__content :deep(ul),
.aia-bubble__content :deep(ol) { padding-inline-start: 1.5rem; margin: 0.25rem 0; }
.aia-bubble__content :deep(li) { margin: 0.125rem 0; }
.aia-bubble__content :deep(li > ul),
.aia-bubble__content :deep(li > ol) { margin: 0.125rem 0; }
/* Headings — marked.parse turns ``# Foo`` / ``## Foo`` / ... into
   ``<h1>..<h6>`` elements. Without explicit styling the dark-theme
   bubble inherits the page's heading reset (or none) and the heading
   looks indistinguishable from body text, so the user reports
   "markdown isn't rendering". Stage these progressively from h1 down
   so the visual hierarchy is preserved inside a chat bubble (smaller
   than the page-level headings to avoid dwarfing the surrounding
   text). */
.aia-bubble__content :deep(h1),
.aia-bubble__content :deep(h2),
.aia-bubble__content :deep(h3),
.aia-bubble__content :deep(h4),
.aia-bubble__content :deep(h5),
.aia-bubble__content :deep(h6) {
  font-weight: 700;
  line-height: 1.25;
  margin: 0.75rem 0 0.35rem;
  color: var(--aia-fg, #fafafa);
}
.aia-bubble__content :deep(h1) { font-size: 1.35rem; }
.aia-bubble__content :deep(h2) { font-size: 1.15rem; }
.aia-bubble__content :deep(h3) { font-size: 1.0rem;  }
.aia-bubble__content :deep(h4) { font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--aia-fg-muted, #a1a1aa); }
.aia-bubble__content :deep(h5),
.aia-bubble__content :deep(h6) { font-size: 0.9rem;  color: var(--aia-fg-muted, #a1a1aa); }
.aia-bubble__content :deep(h1):first-child,
.aia-bubble__content :deep(h2):first-child,
.aia-bubble__content :deep(h3):first-child { margin-top: 0; }
/* Blockquotes, tables, hr, strong / em / a — without these the
   default UA styling is invisible against the bubble bg. */
.aia-bubble__content :deep(blockquote) {
  border-left: 3px solid var(--aia-border-strong, #3f3f46);
  padding: 0.15rem 0.6rem;
  margin: 0.4rem 0;
  color: var(--aia-fg-muted, #a1a1aa);
}
.aia-bubble__content :deep(table) {
  border-collapse: collapse;
  margin: 0.5rem 0;
  font-size: 0.85rem;
}
.aia-bubble__content :deep(th),
.aia-bubble__content :deep(td) {
  border: 1px solid var(--aia-border, #27272a);
  padding: 0.3rem 0.55rem;
  text-align: left;
}
.aia-bubble__content :deep(th) {
  background: var(--aia-bg-hover, #1f1f1f);
  font-weight: 600;
}
.aia-bubble__content :deep(hr) {
  border: 0;
  border-top: 1px solid var(--aia-border, #27272a);
  margin: 0.6rem 0;
}
.aia-bubble__content :deep(a) {
  color: var(--aia-link, #60a5fa);
  text-decoration: underline;
}
.aia-bubble__content :deep(a:hover) { text-decoration: none; }
.aia-bubble__content :deep(strong) { color: var(--aia-fg, #fafafa); }
.aia-bubble__content :deep(em) { font-style: italic; }
.aia-bubble--streaming .aia-bubble__content::after { content: '\25AE'; animation: aia-blink 1s step-end infinite; }
@keyframes aia-blink { 50% { opacity: 0; } }
/* Fade-in animation: 350ms opacity 0->1 + translateY(8px)->0.
 * Back-migrated from Agented MessageBubble. Suppressed when
 * `skipTransition` is set (mass historical-render case). */
.aia-bubble--fade-in { animation: aia-bubble-fade-in 350ms ease-out both; }
@keyframes aia-bubble-fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
/* Avatar SVG sizing — applies when `avatarPaths` prop renders an SVG. */
.aia-bubble__avatar svg { width: 18px; height: 18px; }
</style>
