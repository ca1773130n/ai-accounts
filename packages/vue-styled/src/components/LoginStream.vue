<script setup lang="ts">
import { ref, watch } from 'vue';
import type { UseLoginSession } from '@ai-accounts/vue-headless';

const props = withDefaults(
  defineProps<{
    session: UseLoginSession;
    showStdout?: boolean;
  }>(),
  { showStdout: true }
);

const answer = ref('');

async function submit() {
  const value = answer.value;
  answer.value = '';
  await props.session.respond(value);
}

async function selectMenuOption(number: number) {
  await props.session.respond(String(number));
}

// Auto-open OAuth URLs in the user's browser when they arrive
let lastOpenedUrl = '';
watch(
  () => props.session.urlPrompt.value?.url,
  (url) => {
    if (url && url !== lastOpenedUrl) {
      lastOpenedUrl = url;
      window.open(url, '_blank', 'noopener');
    }
  },
  { immediate: true },
);
</script>

<template>
  <div class="aia-login-stream">
    <!-- OAuth URL -->
    <div v-if="session.urlPrompt.value" class="aia-url-section">
      <div class="aia-url-badge">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
          <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
        <span>A browser window should have opened. If not, click the link below:</span>
      </div>
      <a :href="session.urlPrompt.value.url" target="_blank" rel="noopener" class="aia-url-link">
        {{ session.urlPrompt.value.url }}
      </a>
      <div v-if="session.urlPrompt.value.user_code" class="aia-device-code">
        <span class="aia-device-code__label">Your device code:</span>
        <code class="aia-device-code__value">{{ session.urlPrompt.value.user_code }}</code>
      </div>
    </div>

    <!-- Menu Options -->
    <div v-if="session.menuPrompt.value" class="aia-menu-section">
      <p class="aia-menu-section__title">{{ session.menuPrompt.value.prompt }}</p>
      <div class="aia-menu-options">
        <button
          v-for="opt in session.menuPrompt.value.options"
          :key="opt.number"
          type="button"
          class="aia-menu-option"
          @click="selectMenuOption(opt.number)"
        >
          <span class="aia-menu-option__num">{{ opt.number }}</span>
          <div class="aia-menu-option__body">
            <span class="aia-menu-option__label">{{ opt.label }}</span>
            <span v-if="opt.description" class="aia-menu-option__desc">{{ opt.description }}</span>
          </div>
          <svg class="aia-menu-option__arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Text Input Prompt -->
    <form v-if="session.textPrompt.value" class="aia-text-section" @submit.prevent="submit">
      <label class="aia-text-section__label">{{ session.textPrompt.value.prompt }}</label>
      <div class="aia-text-section__row">
        <span class="aia-text-section__prompt">&gt;</span>
        <input
          v-model="answer"
          class="aia-text-section__input"
          :type="session.textPrompt.value.hidden ? 'password' : 'text'"
          :placeholder="session.textPrompt.value.hidden ? '••••••••' : 'Type here…'"
          autocomplete="off"
          autofocus
        />
        <button type="submit" class="aia-text-section__btn" :disabled="!answer.trim()">Send</button>
      </div>
    </form>

    <!-- Terminal Output -->
    <div v-if="showStdout && session.stdoutLines.value.length > 0" class="aia-terminal">
      <div class="aia-terminal__output">
        <div v-for="(line, i) in session.stdoutLines.value" :key="i" class="aia-terminal__line">{{ line }}</div>
      </div>
    </div>

    <!-- Error -->
    <div v-if="session.status.value === 'failed'" class="aia-error-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
        <circle cx="12" cy="12" r="10" />
        <line x1="15" y1="9" x2="9" y2="15" />
        <line x1="9" y1="9" x2="15" y2="15" />
      </svg>
      <div>
        <strong>{{ session.errorCode.value }}</strong>
        <p>{{ session.errorMessage.value }}</p>
      </div>
    </div>

    <!-- Cancel -->
    <button
      v-if="session.status.value === 'running'"
      type="button"
      class="aia-cancel-btn"
      @click="session.cancel()"
    >
      Cancel
    </button>
  </div>
</template>

<style scoped>
.aia-login-stream {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  font-family: var(--aia-font-sans, system-ui, -apple-system, sans-serif);
  color: var(--text-primary, var(--aia-fg, #fafafa));
}

/* ── URL Section ── */
.aia-url-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.aia-url-badge {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 0.875rem;
  background: rgba(96, 165, 250, 0.1);
  border: 1px solid rgba(96, 165, 250, 0.2);
  border-radius: 8px;
  font-size: 0.8125rem;
  color: var(--accent-cyan, #60a5fa);
}
.aia-url-link {
  display: block;
  padding: 0.625rem 0.875rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-default, var(--aia-border, #27272a));
  border-radius: 8px;
  font-family: var(--aia-font-mono, 'SF Mono', Monaco, monospace);
  font-size: 0.75rem;
  color: var(--accent-cyan, var(--aia-primary, #60a5fa));
  word-break: break-all;
  text-decoration: none;
  transition: border-color 0.15s;
}
.aia-url-link:hover {
  border-color: var(--accent-cyan, var(--aia-primary, #60a5fa));
}
.aia-device-code {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-default, var(--aia-border, #27272a));
  border-radius: 8px;
}
.aia-device-code__label {
  font-size: 0.8125rem;
  color: var(--text-secondary, var(--aia-fg-muted, #a1a1aa));
}
.aia-device-code__value {
  font-family: var(--aia-font-mono, 'SF Mono', Monaco, monospace);
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--text-primary, var(--aia-fg, #e4e4e7));
  padding: 0.375rem 1rem;
  background: var(--bg-tertiary, rgba(0, 0, 0, 0.4));
  border-radius: 6px;
}

/* ── Menu Options ── */
.aia-menu-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.aia-menu-section__title {
  margin: 0;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-secondary, var(--aia-fg-muted, #a1a1aa));
}
.aia-menu-options {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.aia-menu-option {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: var(--bg-secondary, var(--aia-bg-elevated, #141414));
  border: 1px solid var(--border-default, var(--aia-border, #27272a));
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  color: inherit;
  transition: border-color 0.15s, background 0.15s;
}
.aia-menu-option:hover {
  border-color: var(--accent-cyan, var(--aia-primary, #60a5fa));
  background: rgba(0, 207, 253, 0.05);
}
.aia-menu-option__num {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: var(--bg-tertiary, rgba(0, 0, 0, 0.3));
  color: var(--text-secondary, var(--aia-fg-muted, #a1a1aa));
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
}
.aia-menu-option__body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  flex: 1;
}
.aia-menu-option__label {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary, var(--aia-fg, #fafafa));
}
.aia-menu-option__desc {
  font-size: 0.75rem;
  color: var(--text-secondary, var(--aia-fg-muted, #a1a1aa));
}
.aia-menu-option__arrow {
  color: var(--text-tertiary, var(--aia-fg-subtle, #52525b));
  flex-shrink: 0;
}

/* ── Text Input ── */
.aia-text-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.aia-text-section__label {
  font-size: 0.8125rem;
  color: var(--text-secondary, var(--aia-fg-muted, #a1a1aa));
}
.aia-text-section__row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-default, var(--aia-border, #27272a));
  border-radius: 8px;
}
.aia-text-section__prompt {
  color: var(--accent-cyan, #60a5fa);
  font-family: var(--aia-font-mono, monospace);
  font-weight: 600;
  flex-shrink: 0;
}
.aia-text-section__input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-primary, var(--aia-fg, #fafafa));
  font-family: var(--aia-font-mono, monospace);
  font-size: 0.8125rem;
  outline: none;
}
.aia-text-section__input::placeholder {
  color: var(--text-tertiary, #52525b);
}
.aia-text-section__btn {
  padding: 0.375rem 0.75rem;
  background: var(--primary-color, var(--aia-primary, #7c3aed));
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s;
}
.aia-text-section__btn:hover {
  background: var(--primary-hover, var(--aia-primary-hover, #8b5cf6));
}
.aia-text-section__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── Terminal Output ── */
.aia-terminal {
  background: #0a0a0f;
  border: 1px solid var(--border-default, var(--aia-border, #27272a));
  border-radius: 8px;
  overflow: hidden;
}
.aia-terminal__output {
  padding: 0.75rem 1rem;
  font-family: var(--aia-font-mono, 'SF Mono', Monaco, monospace);
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text-tertiary, #71717a);
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.aia-terminal__line {
  min-height: 1.2em;
}

/* ── Error ── */
.aia-error-card {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  font-size: 0.8125rem;
  color: var(--accent-crimson, #ef4444);
}
.aia-error-card p { margin: 0.25rem 0 0; }
.aia-error-card strong { font-weight: 600; }

/* ── Cancel ── */
.aia-cancel-btn {
  align-self: flex-start;
  padding: 0.375rem 0.75rem;
  background: transparent;
  border: 1px solid var(--border-default, var(--aia-border, #27272a));
  border-radius: 6px;
  color: var(--text-secondary, var(--aia-fg-muted, #a1a1aa));
  font-size: 0.8125rem;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.aia-cancel-btn:hover {
  background: var(--bg-secondary, rgba(255, 255, 255, 0.05));
  color: var(--text-primary, var(--aia-fg, #fafafa));
}
</style>
