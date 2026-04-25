<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { UseLoginSession } from '@ai-accounts/vue-headless';
import { forceFreshAccountPrompt } from './forceFreshAccountPrompt';

const props = withDefaults(
  defineProps<{
    session: UseLoginSession;
    /**
     * Render the raw CLI terminal output behind the wizard prompts.
     * Defaults to ``false`` because end-users complained about the
     * leaked Claude/Codex/Gemini CLI screen being noisy and confusing.
     * Set to ``true`` from a debugging surface (e.g. an admin console)
     * if you want to see what the underlying PTY is emitting.
     */
    showStdout?: boolean;
    /**
     * Backend kind — used to decide which OAuth flavor (Google vs Claude)
     * to force into a fresh account-picker prompt.
     */
    backendKind?: string;
    /** Optional email to pass as `login_hint` on the OAuth URL. */
    email?: string;
  }>(),
  { showStdout: false, backendKind: '', email: '' }
);

const answer = ref('');
const eagerCode = ref('');
const eagerStatus = ref<'idle' | 'queued' | 'sent'>('idle');
let queuedCode: string | null = null;

// True between code submit and terminal login status (complete/failed).
// Shows a "Verifying..." indicator so the wizard doesn't look frozen
// while Claude CLI validates the OAuth code against the provider.
const verifying = computed(() =>
  eagerStatus.value === 'sent' && props.session.status.value === 'running'
);

async function submit() {
  const value = answer.value;
  answer.value = '';
  eagerStatus.value = 'sent';
  await props.session.respond(value);
}

/**
 * Eager submit: user pastes the OAuth code as soon as they get it
 * from the browser, BEFORE the CLI emits its "Paste code here if
 * prompted >" text prompt. Claude v2's `auth login --claudeai`
 * takes ~10 seconds to print the paste prompt — and sometimes never
 * emits it at all. We bypass the textPrompt path entirely and write
 * directly to the CLI's stdin via writeEager, which the CLI consumes
 * once its internal read fires.
 */
async function submitEagerCode() {
  const value = eagerCode.value.trim();
  if (!value) return;
  eagerCode.value = '';
  eagerStatus.value = 'sent';
  try {
    await props.session.writeEager(value);
  } catch {
    // If write fails, fall back to respond once a text prompt arrives.
    queuedCode = value;
    eagerStatus.value = 'queued';
  }
}

// Fallback: if writeEager isn't available and textPrompt arrives, flush.
watch(
  () => props.session.textPrompt.value,
  async (prompt) => {
    if (prompt && queuedCode) {
      const code = queuedCode;
      queuedCode = null;
      eagerStatus.value = 'sent';
      await props.session.respond(code);
    }
  },
);

async function selectMenuOption(number: number) {
  await props.session.respond(String(number));
}

/**
 * OAuth URL with force-fresh-prompt params appended. Mirrors Agented
 * f52c55a: Google backends get `prompt=select_account consent`, Claude
 * gets `prompt=login`; both get a `login_hint` when an email is known.
 */
const effectiveOauthUrl = computed(() => {
  const raw = props.session.urlPrompt.value?.url;
  if (!raw) return '';
  const provider =
    props.backendKind === 'gemini' || props.backendKind === 'codex'
      ? 'google'
      : props.backendKind === 'claude'
        ? 'claude'
        : 'none';
  if (provider === 'none') return raw;
  return forceFreshAccountPrompt(raw, props.email ?? '', provider);
});

// Auto-open OAuth URLs in the user's browser when they arrive.
// We open the *effective* (force-fresh) URL so the correct account
// picker is shown even when the user's default browser is signed in.
let lastOpenedUrl = '';
watch(
  () => effectiveOauthUrl.value,
  (url) => {
    if (url && url !== lastOpenedUrl) {
      lastOpenedUrl = url;
      window.open(url, '_blank', 'noopener');
    }
  },
  { immediate: true },
);

// ── Incognito URL copy ────────────────────────────────────────────────
// Users may be signed into the wrong Google account in their default
// browser. Copying the URL + pasting into an incognito window forces a
// clean re-auth. The hint box is toggled on-click and dismissible.
const urlCopied = ref(false);
const showIncognitoHint = ref(false);
let copyTimer: ReturnType<typeof setTimeout> | null = null;

async function copyForIncognito() {
  const url = effectiveOauthUrl.value;
  if (!url) return;
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
    }
    urlCopied.value = true;
    showIncognitoHint.value = true;
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      urlCopied.value = false;
    }, 2500);
  } catch {
    // Clipboard may be unavailable (insecure origin, older browsers).
    // Still surface the hint so the user can manually copy the link.
    showIncognitoHint.value = true;
  }
}

function dismissIncognitoHint() {
  showIncognitoHint.value = false;
}
</script>

<template>
  <div class="aia-login-stream" data-tour="wiz-login-stream">
    <!-- Preparing-CLI spinner: shown while the session is running but no
         actionable prompt has arrived yet (CLI launching, theme picker
         being auto-dismissed, OAuth URL not yet emitted). Without this,
         the wizard looked frozen during the 5–15 seconds between
         "click option 1" and "OAuth URL appears". -->
    <div
      v-if="
        !session.urlPrompt.value &&
        !session.menuPrompt.value &&
        !session.textPrompt.value &&
        session.status.value === 'running' &&
        !verifying
      "
      class="aia-preparing"
    >
      <span class="aia-preparing__spinner"></span>
      <div class="aia-preparing__text">
        <strong>Preparing sign-in…</strong>
        <span>Launching the CLI and waiting for the OAuth link. This usually takes a few seconds.</span>
      </div>
    </div>

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
      <a :href="effectiveOauthUrl" target="_blank" rel="noopener" class="aia-url-link" data-tour="wiz-login-url">
        {{ effectiveOauthUrl }}
      </a>

      <!-- Copy for Incognito — lets users paste the URL into a clean session
           when their default browser is signed into the wrong account. -->
      <div class="aia-url-actions">
        <button
          type="button"
          class="aia-copy-incognito-btn"
          :class="{ 'aia-copy-incognito-btn--copied': urlCopied }"
          :aria-pressed="showIncognitoHint"
          @click="copyForIncognito"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
          <span>{{ urlCopied ? 'Copied!' : 'Copy for Incognito' }}</span>
        </button>
      </div>

      <div v-if="showIncognitoHint" class="aia-incognito-hint">
        <button
          type="button"
          class="aia-incognito-hint__close"
          aria-label="Dismiss"
          @click="dismissIncognitoHint"
        >&times;</button>
        <strong class="aia-incognito-hint__title">Open in an incognito window</strong>
        <p class="aia-incognito-hint__body">
          Press <kbd>&#8984;</kbd><kbd>&#8679;</kbd><kbd>N</kbd> (Mac) or
          <kbd>Ctrl</kbd><kbd>Shift</kbd><kbd>N</kbd> (Windows / Linux) to
          open an incognito window, then paste the URL.
        </p>
      </div>

      <div v-if="session.urlPrompt.value.user_code" class="aia-device-code">
        <span class="aia-device-code__label">Your device code:</span>
        <code class="aia-device-code__value">{{ session.urlPrompt.value.user_code }}</code>
      </div>

      <!-- Eager paste-code input. Shown as soon as the OAuth URL arrives,
           before the underlying CLI has had a chance to emit its own
           "Paste code here if prompted >" prompt. CLIs like Claude v2
           always require the user to paste the code back from the OAuth
           callback page, and the paste-input timing is unreliable across
           CLI versions. Submitting here writes the code to the PTY the
           same way the textPrompt response does. -->
      <!-- Verifying indicator: shown after the user submits a code and
           the CLI is validating it with the OAuth provider. Gives the
           wizard visible progress so it doesn't look frozen. -->
      <div v-if="verifying" class="aia-verifying">
        <span class="aia-verifying__spinner"></span>
        <span class="aia-verifying__text">Verifying authorization code…</span>
      </div>

      <form v-if="!session.textPrompt.value && eagerStatus !== 'sent'" class="aia-text-section aia-text-section--eager" data-tour="wiz-login-paste" @submit.prevent="submitEagerCode">
        <label class="aia-text-section__label">
          After signing in, paste the authorization code here:
          <span v-if="eagerStatus === 'queued'" class="aia-text-section__queued">(queued — waiting for CLI prompt)</span>
        </label>
        <div class="aia-text-section__row">
          <span class="aia-text-section__prompt">&gt;</span>
          <input
            v-model="eagerCode"
            class="aia-text-section__input"
            type="text"
            placeholder="Paste code from browser…"
            autocomplete="off"
            autofocus
            :disabled="eagerStatus === 'queued'"
          />
          <button type="submit" class="aia-text-section__btn" :disabled="!eagerCode.trim() || eagerStatus === 'queued'">
            {{ eagerStatus === 'queued' ? 'Waiting…' : 'Send' }}
          </button>
        </div>
      </form>
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

/* ── Incognito URL copy ── */
.aia-url-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.aia-copy-incognito-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  background: rgba(139, 92, 246, 0.1);
  border: 1px solid rgba(139, 92, 246, 0.35);
  border-radius: 6px;
  color: #a78bfa;
  font-size: 0.8125rem;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.aia-copy-incognito-btn:hover {
  background: rgba(139, 92, 246, 0.18);
  border-color: rgba(139, 92, 246, 0.6);
  color: #c4b5fd;
}
.aia-copy-incognito-btn--copied {
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.45);
  color: #4ade80;
}
.aia-verifying {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-top: 10px;
  border: 1px solid rgba(139, 92, 246, 0.4);
  border-radius: 6px;
  background: rgba(139, 92, 246, 0.08);
  color: var(--aia-fg, #fafafa);
  font-size: 13px;
}
.aia-verifying__spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(139, 92, 246, 0.3);
  border-top-color: #a78bfa;
  border-radius: 50%;
  animation: aia-verifying-spin 0.7s linear infinite;
}
@keyframes aia-verifying-spin {
  to { transform: rotate(360deg); }
}

.aia-preparing {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid rgba(0, 212, 255, 0.35);
  border-radius: 8px;
  background: rgba(0, 212, 255, 0.06);
  color: var(--aia-fg, #fafafa);
}
.aia-preparing__spinner {
  display: inline-block;
  flex: 0 0 18px;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(0, 212, 255, 0.25);
  border-top-color: #00d4ff;
  border-radius: 50%;
  animation: aia-verifying-spin 0.7s linear infinite;
}
.aia-preparing__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
  line-height: 1.4;
}
.aia-preparing__text strong {
  font-weight: 600;
  color: var(--aia-fg, #fafafa);
}
.aia-preparing__text span {
  color: var(--aia-fg-muted, #a0a0b0);
  font-size: 12px;
}
.aia-incognito-hint {
  position: relative;
  padding: 0.75rem 2rem 0.75rem 0.875rem;
  background: rgba(139, 92, 246, 0.08);
  border: 1px solid rgba(139, 92, 246, 0.45);
  border-radius: 8px;
  color: var(--text-primary, #e4e4e7);
  font-size: 0.8125rem;
  line-height: 1.5;
}
.aia-incognito-hint__title {
  display: block;
  margin-bottom: 0.25rem;
  color: #c4b5fd;
  font-weight: 600;
  font-size: 0.8125rem;
}
.aia-incognito-hint__body {
  margin: 0;
  color: var(--text-secondary, #a1a1aa);
}
.aia-incognito-hint__body kbd {
  display: inline-block;
  margin: 0 0.125rem;
  padding: 0.0625rem 0.375rem;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(139, 92, 246, 0.3);
  border-radius: 4px;
  font-family: var(--aia-font-mono, 'SF Mono', Monaco, monospace);
  font-size: 0.75rem;
  color: #c4b5fd;
}
.aia-incognito-hint__close {
  position: absolute;
  top: 0.25rem;
  right: 0.375rem;
  width: 20px;
  height: 20px;
  padding: 0;
  background: transparent;
  border: none;
  color: var(--text-tertiary, #71717a);
  font-size: 1.125rem;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s;
}
.aia-incognito-hint__close:hover {
  color: var(--text-primary, #e4e4e7);
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
.aia-text-section__queued {
  margin-left: 6px;
  font-size: 12px;
  color: #fbbf24;
  font-weight: normal;
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
