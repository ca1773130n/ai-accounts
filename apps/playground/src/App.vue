<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useAiAccounts } from '@ai-accounts/vue-headless';
import { AccountWizard } from '@ai-accounts/vue-styled';

type Backend = {
  id: string;
  kind: string;
  display_name: string;
  status: string;
  config?: Record<string, unknown>;
};

const { client } = useAiAccounts();
const accounts = ref<Backend[]>([]);
const showWizard = ref(false);
const lastSavedId = ref<string | null>(null);

async function refresh() {
  const { items } = await client.listBackends();
  accounts.value = items as unknown as Backend[];
}

function openWizard() {
  lastSavedId.value = null;
  showWizard.value = true;
}

async function onDone(payload: { accountId: string }) {
  lastSavedId.value = payload.accountId;
  showWizard.value = false;
  await refresh();
}

function onClose() {
  showWizard.value = false;
}

onMounted(refresh);
</script>

<template>
  <main class="playground">
    <header class="header">
      <h1>ai-accounts playground</h1>
      <p class="intro">
        Add accounts via OAuth or API key. Each account gets its own config
        directory under your home (e.g. <code>~/.claude-personal</code>).
      </p>
    </header>

    <section class="accounts">
      <div class="accounts__head">
        <h2>Accounts ({{ accounts.length }})</h2>
        <button class="btn btn--primary" @click="openWizard">
          + Add account
        </button>
      </div>

      <ul v-if="accounts.length" class="account-list">
        <li
          v-for="acc in accounts"
          :key="acc.id"
          class="account-row"
          :class="{ 'account-row--new': acc.id === lastSavedId }"
        >
          <div class="account-row__main">
            <strong>{{ acc.display_name }}</strong>
            <span class="account-row__kind">{{ acc.kind }}</span>
            <span
              class="account-row__status"
              :class="`status--${acc.status}`"
            >
              {{ acc.status }}
            </span>
          </div>
          <div class="account-row__meta">
            <code>{{ acc.id }}</code>
            <code v-if="acc.config?.config_path">
              {{ acc.config.config_path }}
            </code>
          </div>
        </li>
      </ul>
      <p v-else class="empty">No accounts yet. Click <em>+ Add account</em> to create one.</p>
    </section>

    <div v-if="showWizard" class="wizard-modal">
      <div class="wizard-modal__panel">
        <AccountWizard
          :allow-skip="false"
          @done="onDone"
          @close="onClose"
        />
      </div>
    </div>
  </main>
</template>

<style>
.playground {
  max-width: 720px;
  margin: 60px auto;
  padding: 0 20px;
  color: var(--aia-fg, #fafafa);
  font-family: var(--aia-font-sans, system-ui, sans-serif);
}

.header h1 {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.intro {
  color: var(--aia-fg-muted, #a1a1aa);
  margin-bottom: 2rem;
  line-height: 1.6;
}

code {
  font-family: var(--aia-font-mono, monospace);
  background: var(--aia-bg-elevated, #141414);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85em;
}

.accounts__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.btn {
  background: var(--aia-bg-elevated, #1f1f23);
  color: var(--aia-fg, #fafafa);
  border: 1px solid var(--aia-border, #2a2a2e);
  padding: 8px 16px;
  border-radius: 6px;
  font: inherit;
  cursor: pointer;
}

.btn--primary {
  background: var(--aia-accent, #3b82f6);
  border-color: var(--aia-accent, #3b82f6);
  color: #fff;
}

.account-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
}

.account-row {
  background: var(--aia-bg-elevated, #141414);
  border: 1px solid var(--aia-border, #2a2a2e);
  border-radius: 8px;
  padding: 12px 14px;
  display: grid;
  gap: 4px;
}

.account-row--new {
  border-color: var(--aia-success, #10b981);
}

.account-row__main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.account-row__kind {
  font-size: 0.8em;
  text-transform: uppercase;
  color: var(--aia-fg-muted, #a1a1aa);
}

.account-row__status {
  font-size: 0.75em;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--aia-bg, #0a0a0a);
  border: 1px solid var(--aia-border, #2a2a2e);
}

.status--ready { color: var(--aia-success, #10b981); }
.status--error { color: var(--aia-danger, #ef4444); }

.account-row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.85em;
  color: var(--aia-fg-muted, #a1a1aa);
}

.empty {
  color: var(--aia-fg-muted, #a1a1aa);
  font-style: italic;
}

.wizard-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 20px;
  z-index: 100;
  overflow: auto;
}

.wizard-modal__panel {
  background: var(--aia-bg, #0a0a0a);
  border: 1px solid var(--aia-border, #2a2a2e);
  border-radius: 12px;
  padding: 24px;
  width: 100%;
  max-width: 640px;
}
</style>
