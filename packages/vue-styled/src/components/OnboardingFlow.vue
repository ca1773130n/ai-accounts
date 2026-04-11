<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useOnboarding } from '@ai-accounts/vue-headless';
import type { AiAccountsClient } from '@ai-accounts/ts-core';

const props = defineProps<{
  client: AiAccountsClient;
  kinds?: Array<{ id: string; display: string }>;
  supportedFlowsByKind?: Record<string, string[]>;
}>();

const emit = defineEmits<{
  done: [backendId: string];
  cancel: [];
}>();

const wiz = useOnboarding({ client: props.client });
const apiKey = ref('');
const loginTab = ref<'api_key' | 'oauth_device'>('api_key');

const DEFAULT_KINDS = [
  { id: 'claude', display: 'Claude' },
  { id: 'opencode', display: 'OpenCode' },
  { id: 'gemini', display: 'Gemini' },
  { id: 'codex', display: 'Codex' },
];

const DEFAULT_SUPPORTED_FLOWS: Record<string, string[]> = {
  claude: ['api_key'],
  opencode: ['api_key'],
  gemini: ['api_key', 'oauth_device'],
  codex: ['api_key', 'oauth_device'],
};

const displayKinds = computed(() => props.kinds ?? DEFAULT_KINDS);
const supportedFlowsMap = computed(
  () => props.supportedFlowsByKind ?? DEFAULT_SUPPORTED_FLOWS
);

const supportedFlowsForSelected = computed(() => {
  const k = wiz.selectedKind.value;
  if (!k) return ['api_key'];
  return supportedFlowsMap.value[k] ?? ['api_key'];
});

async function onStart() {
  await wiz.start();
  if (wiz.state.value === 'error') return;
  await wiz.detect();
}

async function onPick(kind: string) {
  await wiz.pickKind(kind);
  // Default tab to the first supported flow for the chosen kind
  const flows = supportedFlowsForSelected.value;
  loginTab.value = (flows[0] ?? 'api_key') as 'api_key' | 'oauth_device';
}

async function onSubmitApiKey() {
  await wiz.submitApiKey(apiKey.value);
}

async function onSubmitOauth() {
  await wiz.submitOauthDevice();
}

watch(
  () => wiz.state.value,
  (s) => {
    if (s === 'done' && wiz.createdBackendId.value) {
      emit('done', wiz.createdBackendId.value);
    }
  },
  { immediate: false }
);

function onRetry() {
  wiz.reset();
}

function onCopyCode() {
  const code = wiz.oauthChallenge.value?.user_code;
  if (code && typeof navigator !== 'undefined' && navigator.clipboard) {
    void navigator.clipboard.writeText(code);
  }
}

function detectionForKind(id: string) {
  return wiz.kinds.value?.find((k) => k.id === id)?.detection;
}
</script>

<template>
  <section class="aia-onboarding">
    <header class="aia-onboarding__header">
      <slot name="header">
        <h2>Set up an AI backend</h2>
      </slot>
    </header>

    <!-- idle / welcome -->
    <div v-if="wiz.state.value === 'idle'" class="aia-onboarding__welcome">
      <p>Connect one of the supported AI CLIs to get started.</p>
      <button type="button" class="aia-btn aia-btn--primary" @click="onStart">
        Get started
      </button>
    </div>

    <div
      v-else-if="wiz.state.value === 'started' || wiz.state.value === 'detecting'"
      class="aia-onboarding__status"
    >
      Detecting installed CLIs&hellip;
    </div>

    <!-- picking_kind -->
    <div v-else-if="wiz.state.value === 'picking_kind'" class="aia-onboarding__kind-grid">
      <button
        v-for="k in displayKinds"
        :key="k.id"
        type="button"
        class="aia-kind-card"
        :class="{
          'aia-kind-card--installed': detectionForKind(k.id)?.installed,
          'aia-kind-card--missing':
            detectionForKind(k.id) && !detectionForKind(k.id)?.installed,
        }"
        :disabled="!detectionForKind(k.id)?.installed"
        @click="onPick(k.id)"
      >
        <span class="aia-kind-card__name">{{ k.display }}</span>
        <span v-if="detectionForKind(k.id)?.installed" class="aia-kind-card__badge">
          Installed
        </span>
        <span v-else class="aia-kind-card__badge aia-kind-card__badge--missing">
          Not installed
        </span>
      </button>
    </div>

    <!-- entering_credential -->
    <div v-else-if="wiz.state.value === 'entering_credential'" class="aia-onboarding__login">
      <div class="aia-onboarding__tabs">
        <button
          v-if="supportedFlowsForSelected.includes('api_key')"
          type="button"
          class="aia-tab"
          :class="{ 'aia-tab--active': loginTab === 'api_key' }"
          @click="loginTab = 'api_key'"
        >
          API key
        </button>
        <button
          v-if="supportedFlowsForSelected.includes('oauth_device')"
          type="button"
          class="aia-tab"
          :class="{ 'aia-tab--active': loginTab === 'oauth_device' }"
          @click="loginTab = 'oauth_device'"
        >
          Login with browser
        </button>
      </div>

      <form
        v-if="loginTab === 'api_key'"
        class="aia-onboarding__form"
        @submit.prevent="onSubmitApiKey"
      >
        <label class="aia-label">
          API key
          <input
            v-model="apiKey"
            type="password"
            class="aia-input"
            autocomplete="off"
            required
          />
        </label>
        <button type="submit" class="aia-btn aia-btn--primary">Connect</button>
      </form>

      <div v-else-if="loginTab === 'oauth_device'" class="aia-onboarding__oauth-start">
        <p>You'll be shown a verification URL and code. Open it in your browser to sign in.</p>
        <button type="button" class="aia-btn aia-btn--primary" @click="onSubmitOauth">
          Start browser login
        </button>
      </div>
    </div>

    <!-- oauth_challenge / oauth_polling -->
    <div
      v-else-if="
        wiz.state.value === 'oauth_challenge' || wiz.state.value === 'oauth_polling'
      "
      class="aia-onboarding__oauth-challenge"
    >
      <p>Open this URL in your browser and enter the code:</p>
      <a
        :href="wiz.oauthChallenge.value?.verification_uri"
        target="_blank"
        rel="noopener noreferrer"
        class="aia-onboarding__oauth-uri"
      >
        {{ wiz.oauthChallenge.value?.verification_uri }}
      </a>
      <div class="aia-code-display">
        <code>{{ wiz.oauthChallenge.value?.user_code }}</code>
        <button type="button" class="aia-copy-btn" @click="onCopyCode">Copy</button>
      </div>
      <p class="aia-onboarding__hint">Waiting for you to complete sign-in&hellip;</p>
      <button type="button" class="aia-btn" @click="wiz.cancelOAuth">Cancel</button>
    </div>

    <div v-else-if="wiz.state.value === 'validating'" class="aia-onboarding__status">
      Validating credential&hellip;
    </div>

    <div v-else-if="wiz.state.value === 'done'" class="aia-onboarding__success">
      <slot name="success">
        <p>&#10003; Connected successfully</p>
      </slot>
    </div>

    <div v-else-if="wiz.state.value === 'error'" class="aia-onboarding__error">
      <p>{{ wiz.error.value }}</p>
      <button type="button" class="aia-btn" @click="onRetry">Try again</button>
    </div>
  </section>
</template>

<style scoped>
.aia-onboarding {
  background: var(--aia-bg-elevated);
  border: 1px solid var(--aia-border);
  border-radius: var(--aia-radius-lg);
  padding: var(--aia-space-6);
  font-family: var(--aia-font-sans);
  color: var(--aia-fg);
  max-width: 640px;
}

.aia-onboarding__header h2 {
  margin: 0 0 var(--aia-space-4);
  font-size: var(--aia-text-xl);
}

.aia-onboarding__welcome {
  display: flex;
  flex-direction: column;
  gap: var(--aia-space-4);
}

.aia-onboarding__kind-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--aia-space-3);
}

.aia-kind-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--aia-space-2);
  background: var(--aia-bg);
  color: var(--aia-fg);
  border: 1px solid var(--aia-border);
  border-radius: var(--aia-radius);
  padding: var(--aia-space-4);
  font: inherit;
  cursor: pointer;
  transition: all var(--aia-transition);
}

.aia-kind-card:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.aia-kind-card--installed:hover {
  background: var(--aia-bg-hover);
  border-color: var(--aia-border-hover);
}

.aia-kind-card__name {
  font-size: var(--aia-text-base);
  font-weight: 600;
}

.aia-kind-card__badge {
  font-size: var(--aia-text-xs);
  color: var(--aia-success);
  padding: var(--aia-space-1) var(--aia-space-2);
  background: color-mix(in srgb, var(--aia-success) 15%, transparent);
  border-radius: var(--aia-radius-sm);
}

.aia-kind-card__badge--missing {
  color: var(--aia-fg-muted);
  background: color-mix(in srgb, var(--aia-fg-muted) 15%, transparent);
}

.aia-onboarding__tabs {
  display: flex;
  gap: var(--aia-space-2);
  margin-bottom: var(--aia-space-4);
  border-bottom: 1px solid var(--aia-border);
}

.aia-tab {
  background: transparent;
  color: var(--aia-fg-muted);
  border: none;
  border-bottom: 2px solid transparent;
  padding: var(--aia-space-2) var(--aia-space-4);
  font: inherit;
  cursor: pointer;
  transition: all var(--aia-transition);
}

.aia-tab:hover {
  color: var(--aia-fg);
}

.aia-tab--active {
  color: var(--aia-fg);
  border-bottom-color: var(--aia-primary);
}

.aia-onboarding__form,
.aia-onboarding__oauth-start {
  display: flex;
  flex-direction: column;
  gap: var(--aia-space-4);
}

.aia-label {
  display: flex;
  flex-direction: column;
  gap: var(--aia-space-2);
  font-size: var(--aia-text-sm);
  color: var(--aia-fg-muted);
}

.aia-input {
  background: var(--aia-bg);
  color: var(--aia-fg);
  border: 1px solid var(--aia-border);
  border-radius: var(--aia-radius);
  padding: var(--aia-space-3);
  font: inherit;
  font-family: var(--aia-font-mono);
}

.aia-btn {
  background: var(--aia-bg);
  color: var(--aia-fg);
  border: 1px solid var(--aia-border);
  border-radius: var(--aia-radius);
  padding: var(--aia-space-3) var(--aia-space-4);
  font: inherit;
  cursor: pointer;
  transition: all var(--aia-transition);
}

.aia-btn:hover {
  background: var(--aia-bg-hover);
  border-color: var(--aia-border-hover);
}

.aia-btn--primary {
  background: var(--aia-primary);
  color: var(--aia-primary-fg);
  border-color: var(--aia-primary);
}

.aia-btn--primary:hover {
  background: var(--aia-primary-hover);
}

.aia-onboarding__oauth-challenge {
  display: flex;
  flex-direction: column;
  gap: var(--aia-space-4);
}

.aia-onboarding__oauth-uri {
  color: var(--aia-primary);
  font-family: var(--aia-font-mono);
  word-break: break-all;
}

.aia-code-display {
  display: flex;
  align-items: center;
  gap: var(--aia-space-3);
  background: var(--aia-bg);
  border: 1px solid var(--aia-border);
  border-radius: var(--aia-radius);
  padding: var(--aia-space-3);
}

.aia-code-display code {
  flex: 1;
  font-family: var(--aia-font-mono);
  font-size: var(--aia-text-lg);
  font-weight: 600;
  letter-spacing: 0.1em;
}

.aia-copy-btn {
  background: transparent;
  color: var(--aia-fg-muted);
  border: 1px solid var(--aia-border);
  border-radius: var(--aia-radius-sm);
  padding: var(--aia-space-1) var(--aia-space-3);
  font: inherit;
  font-size: var(--aia-text-sm);
  cursor: pointer;
}

.aia-onboarding__hint {
  color: var(--aia-fg-muted);
  font-size: var(--aia-text-sm);
}

.aia-onboarding__status,
.aia-onboarding__success,
.aia-onboarding__error {
  padding: var(--aia-space-4) 0;
}

.aia-onboarding__success {
  color: var(--aia-success);
}

.aia-onboarding__error {
  color: var(--aia-danger);
}
</style>
