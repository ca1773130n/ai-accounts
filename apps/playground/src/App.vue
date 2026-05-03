<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useAiAccounts } from '@ai-accounts/vue-headless';
import { AccountWizard, AiChatPanel } from '@ai-accounts/vue-styled';

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
const removingId = ref<string | null>(null);

const readyCount = computed(() => accounts.value.filter(a => a.status === 'ready').length);

async function refresh() {
  const { items } = await client.listBackends();
  accounts.value = items as unknown as Backend[];
}

async function removeAccount(acc: Backend) {
  const ok = window.confirm(
    `Remove "${acc.display_name}" (${acc.kind})?\n\n` +
      `This unregisters the account from the playground. Files under the ` +
      `backend's config directory are NOT deleted.`,
  );
  if (!ok) return;
  removingId.value = acc.id;
  try {
    await client.deleteBackend(acc.id);
    await refresh();
  } finally {
    removingId.value = null;
  }
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
  <main class="page">
    <header class="page__header">
      <div class="page__title-row">
        <div>
          <h1 class="page__title">ai-accounts playground</h1>
          <p class="page__subtitle">
            Add CLI-backed accounts (Claude, Codex, Gemini, OpenCode), then chat
            through a single panel that routes to whichever one you pick.
          </p>
        </div>
        <button class="btn btn--primary" @click="openWizard">+ Add account</button>
      </div>
    </header>

    <section class="card section">
      <header class="section__head">
        <h2 class="section__title">
          Accounts
          <span class="section__count">{{ readyCount }} / {{ accounts.length }} ready</span>
        </h2>
      </header>

      <ul v-if="accounts.length" class="account-list">
        <li
          v-for="acc in accounts"
          :key="acc.id"
          class="account-row"
          :class="[`account-row--${acc.kind}`, { 'account-row--new': acc.id === lastSavedId }]"
        >
          <div class="account-row__rail" />
          <div class="account-row__body">
            <div class="account-row__main">
              <span class="account-row__kind">{{ acc.kind }}</span>
              <strong class="account-row__name">{{ acc.display_name }}</strong>
              <span class="account-row__status" :class="`status--${acc.status}`">
                <span class="status__dot" />{{ acc.status }}
              </span>
            </div>
            <div class="account-row__meta">
              <code>{{ acc.id }}</code>
              <code v-if="acc.config?.config_path">{{ acc.config.config_path }}</code>
            </div>
          </div>
          <div class="account-row__actions">
            <button
              class="btn btn--ghost btn--danger"
              :disabled="removingId === acc.id"
              @click="removeAccount(acc)"
            >
              {{ removingId === acc.id ? 'Removing…' : 'Remove' }}
            </button>
          </div>
        </li>
      </ul>
      <div v-else class="empty">
        <p>No accounts yet.</p>
        <button class="btn btn--primary" @click="openWizard">+ Add your first account</button>
      </div>
    </section>

    <section v-if="readyCount > 0" class="card section section--chat">
      <header class="section__head">
        <h2 class="section__title">Chat</h2>
        <span class="section__hint">Pick a backend / model from the controls bar to route the next message.</span>
      </header>
      <div class="chat__panel">
        <AiChatPanel density="detailed" />
      </div>
    </section>

    <div v-if="showWizard" class="modal" @click.self="onClose">
      <div class="modal__panel">
        <AccountWizard :allow-skip="false" @done="onDone" @close="onClose" />
      </div>
    </div>
  </main>
</template>

<style>
:root {
  --pg-bg: #0a0a0b;
  --pg-bg-elevated: #131316;
  --pg-bg-hover: #181820;
  --pg-border: #26262d;
  --pg-border-strong: #34343d;
  --pg-fg: #f4f4f5;
  --pg-fg-muted: #a1a1aa;
  --pg-fg-subtle: #71717a;
  --pg-accent: #7c8cf8;
  --pg-accent-hover: #94a3ff;
  --pg-success: #34d399;
  --pg-warning: #fbbf24;
  --pg-danger: #f87171;
  --pg-radius: 10px;
  --pg-radius-sm: 6px;
  --pg-shadow: 0 1px 3px rgba(0, 0, 0, 0.3), 0 1px 2px rgba(0, 0, 0, 0.2);
  --pg-shadow-lg: 0 10px 30px rgba(0, 0, 0, 0.5), 0 4px 8px rgba(0, 0, 0, 0.3);
  --kind-claude: #d97757;
  --kind-codex: #10a37f;
  --kind-gemini: #4285f4;
  --kind-opencode: #a78bfa;
}

html, body, #app {
  background: var(--pg-bg);
  color: var(--pg-fg);
  margin: 0;
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.page {
  max-width: 960px;
  margin: 0 auto;
  padding: 56px 24px 80px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.page__title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.page__title {
  font-size: 1.75rem;
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 8px;
}

.page__subtitle {
  margin: 0;
  color: var(--pg-fg-muted);
  max-width: 56ch;
}

.card {
  background: var(--pg-bg-elevated);
  border: 1px solid var(--pg-border);
  border-radius: var(--pg-radius);
  box-shadow: var(--pg-shadow);
}

.section {
  padding: 20px 24px 24px;
}

.section--chat {
  padding-bottom: 16px;
}

.section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.section__title {
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.section__count {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--pg-fg-muted);
  background: var(--pg-bg);
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--pg-border);
}

.section__hint {
  font-size: 0.85rem;
  color: var(--pg-fg-subtle);
}

/* Buttons */
.btn {
  background: var(--pg-bg);
  color: var(--pg-fg);
  border: 1px solid var(--pg-border);
  padding: 9px 16px;
  border-radius: var(--pg-radius-sm);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
  white-space: nowrap;
}
.btn:hover { background: var(--pg-bg-hover); border-color: var(--pg-border-strong); }

.btn--primary {
  background: var(--pg-accent);
  border-color: var(--pg-accent);
  color: #0a0a0b;
  font-weight: 600;
}
.btn--primary:hover { background: var(--pg-accent-hover); border-color: var(--pg-accent-hover); }

.btn--ghost { background: transparent; }
.btn--ghost:hover { background: var(--pg-bg-hover); }

.btn--danger {
  color: var(--pg-fg-muted);
  border-color: transparent;
}
.btn--danger:hover {
  color: var(--pg-danger);
  border-color: var(--pg-danger);
  background: rgba(248, 113, 113, 0.08);
}
.btn--danger:disabled { opacity: 0.5; cursor: not-allowed; pointer-events: none; }

/* Account list */
.account-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.account-row {
  display: grid;
  grid-template-columns: 4px 1fr auto;
  gap: 16px;
  background: var(--pg-bg);
  border: 1px solid var(--pg-border);
  border-radius: var(--pg-radius-sm);
  padding: 14px 16px 14px 0;
  align-items: center;
  transition: border-color 120ms ease, background 120ms ease;
}
.account-row:hover { background: var(--pg-bg-hover); border-color: var(--pg-border-strong); }
.account-row--new { border-color: var(--pg-success); box-shadow: 0 0 0 1px rgba(52, 211, 153, 0.25); }

.account-row__rail {
  align-self: stretch;
  border-radius: 2px 0 0 2px;
  background: var(--pg-fg-subtle);
}
.account-row--claude .account-row__rail { background: var(--kind-claude); }
.account-row--codex .account-row__rail { background: var(--kind-codex); }
.account-row--gemini .account-row__rail { background: var(--kind-gemini); }
.account-row--opencode .account-row__rail { background: var(--kind-opencode); }

.account-row__body { min-width: 0; display: flex; flex-direction: column; gap: 4px; }

.account-row__main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.account-row__kind {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--pg-fg-muted);
  background: var(--pg-bg-elevated);
  border: 1px solid var(--pg-border);
  border-radius: 4px;
  padding: 2px 8px;
}

.account-row__name {
  font-weight: 600;
  font-size: 0.95rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-row__status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--pg-bg-elevated);
  border: 1px solid var(--pg-border);
}
.status__dot { width: 6px; height: 6px; border-radius: 50%; background: var(--pg-fg-subtle); }
.status--ready { color: var(--pg-success); border-color: rgba(52, 211, 153, 0.3); background: rgba(52, 211, 153, 0.08); }
.status--ready .status__dot { background: var(--pg-success); box-shadow: 0 0 6px var(--pg-success); }
.status--error { color: var(--pg-danger); border-color: rgba(248, 113, 113, 0.3); background: rgba(248, 113, 113, 0.08); }
.status--error .status__dot { background: var(--pg-danger); }
.status--unconfigured { color: var(--pg-warning); border-color: rgba(251, 191, 36, 0.3); background: rgba(251, 191, 36, 0.08); }
.status--unconfigured .status__dot { background: var(--pg-warning); }

.account-row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-size: 0.78rem;
  color: var(--pg-fg-subtle);
}
.account-row__meta code {
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  background: var(--pg-bg-elevated);
  border: 1px solid var(--pg-border);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.78rem;
  color: var(--pg-fg-muted);
}

.account-row__actions { padding-right: 16px; }

/* Empty state */
.empty {
  text-align: center;
  padding: 32px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: var(--pg-fg-muted);
}
.empty p { margin: 0; }

/* Chat panel */
.chat__panel {
  background: var(--pg-bg);
  border: 1px solid var(--pg-border);
  border-radius: var(--pg-radius-sm);
  height: 640px;
  overflow: hidden;
  display: flex;
}
.chat__panel > * { flex: 1; min-width: 0; }

/* Modal */
.modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 20px;
  z-index: 100;
  overflow: auto;
}
.modal__panel {
  background: var(--pg-bg-elevated);
  border: 1px solid var(--pg-border);
  border-radius: var(--pg-radius);
  padding: 24px;
  width: 100%;
  max-width: 680px;
  box-shadow: var(--pg-shadow-lg);
}

@media (max-width: 640px) {
  .page { padding: 32px 16px 60px; }
  .page__title-row { flex-direction: column; align-items: stretch; }
  .section { padding: 16px; }
  .account-row { grid-template-columns: 4px 1fr; padding-right: 0; }
  .account-row__actions { grid-column: 2; padding: 0 0 8px 0; justify-self: end; }
}
</style>
