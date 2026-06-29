<script setup lang="ts">
/**
 * AccountReauth — a "Re-auth" control for an already-registered account.
 *
 * Re-runs the backend's login flow against the *existing* account id, so an
 * expired credential (a lapsed OAuth token, a rotated API key) can be
 * refreshed in place — no need to remove and re-add the account. It reuses the
 * same {@link LoginStream} UI the wizard drives. Supported login flows are
 * resolved from the backend registry; backends that offer more than one let
 * the user pick which to re-authenticate with.
 *
 * Emits `reauthed` with the account id once the login completes — the host can
 * refresh its account list / model dropdowns in response.
 */
import { computed, ref, watch } from 'vue';
import { useBackendRegistry, useLoginSession } from '@ai-accounts/vue-headless';
import type { LoginFlowKind } from '@ai-accounts/ts-core';
import LoginStream from './LoginStream.vue';

const props = defineProps<{
  account: { id: string; kind: string; display_name?: string };
}>();
const emit = defineEmits<{ (e: 'reauthed', accountId: string): void }>();

const registry = useBackendRegistry();
const session = useLoginSession();

const open = ref(false); // login panel visible
const picking = ref(false); // flow chooser visible (multi-flow backends)
const loading = ref(false);

const flows = computed(() => registry.get(props.account.kind)?.login_flows ?? []);
const label = computed(() => props.account.display_name || props.account.id);

async function onReauthClick(): Promise<void> {
  loading.value = true;
  try {
    if (!registry.loaded.value) await registry.load();
  } finally {
    loading.value = false;
  }
  if (flows.value.length > 1) {
    picking.value = true;
  } else {
    await startFlow(flows.value[0]?.kind ?? 'cli_browser');
  }
}

async function startFlow(flow: string): Promise<void> {
  picking.value = false;
  session.reset();
  open.value = true;
  await session.start(props.account.id, flow as LoginFlowKind, {});
}

function close(): void {
  if (session.status.value === 'running') void session.cancel();
  session.reset();
  open.value = false;
  picking.value = false;
}

watch(
  () => session.status.value,
  (s) => {
    if (s === 'complete') emit('reauthed', props.account.id);
  },
);
</script>

<template>
  <div class="aia-reauth">
    <button
      v-if="!open && !picking"
      type="button"
      class="aia-reauth__btn"
      :disabled="loading"
      :title="`Re-authenticate ${label}`"
      @click="onReauthClick"
    >
      <span class="aia-reauth__icon" aria-hidden="true">&#8635;</span>
      {{ loading ? 'Loading…' : 'Re-auth' }}
    </button>

    <!-- multi-flow chooser -->
    <div v-else-if="picking" class="aia-reauth__flows">
      <span class="aia-reauth__flows-label">Sign in via:</span>
      <button
        v-for="f in flows"
        :key="f.kind"
        type="button"
        class="aia-reauth__flow"
        @click="startFlow(f.kind)"
      >
        {{ f.display_name || f.kind }}
      </button>
      <button type="button" class="aia-reauth__flow aia-reauth__flow--ghost" @click="picking = false">
        Cancel
      </button>
    </div>

    <!-- login panel (modal overlay) -->
    <div v-if="open" class="aia-reauth__overlay" @click.self="close">
      <div class="aia-reauth__panel">
        <header class="aia-reauth__head">
          <strong>Re-authenticate {{ label }}</strong>
          <button type="button" class="aia-reauth__close" aria-label="Close" @click="close">&times;</button>
        </header>
        <div v-if="session.status.value === 'complete'" class="aia-reauth__ok">
          <span>&#10003; Re-authenticated.</span>
          <button type="button" class="aia-reauth__flow" @click="close">Done</button>
        </div>
        <LoginStream v-else :session="session" :backend-kind="account.kind" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.aia-reauth {
  display: inline-flex;
}
.aia-reauth__btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 14px;
  background: transparent;
  border: 1px solid var(--aia-border, #27272a);
  border-radius: 6px;
  color: var(--aia-fg-muted, #a1a1aa);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s, background 0.12s;
}
.aia-reauth__btn:hover {
  color: var(--aia-primary, #7c8cf8);
  border-color: var(--aia-primary, #7c8cf8);
  background: rgba(124, 140, 248, 0.08);
}
.aia-reauth__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.aia-reauth__icon {
  font-size: 1rem;
  line-height: 1;
}
.aia-reauth__flows {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.aia-reauth__flows-label {
  font-size: 0.8rem;
  color: var(--aia-fg-muted, #a1a1aa);
}
.aia-reauth__flow {
  padding: 7px 12px;
  background: var(--aia-bg-elevated, #141414);
  border: 1px solid var(--aia-border, #27272a);
  border-radius: 6px;
  color: var(--aia-fg, #fafafa);
  font: inherit;
  cursor: pointer;
}
.aia-reauth__flow:hover {
  border-color: var(--aia-primary, #7c8cf8);
}
.aia-reauth__flow--ghost {
  color: var(--aia-fg-muted, #a1a1aa);
  background: transparent;
}
.aia-reauth__overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 20px;
  overflow: auto;
}
.aia-reauth__panel {
  width: 100%;
  max-width: 560px;
  background: var(--aia-bg-elevated, #131316);
  border: 1px solid var(--aia-border, #27272a);
  border-radius: 10px;
  padding: 20px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}
.aia-reauth__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.aia-reauth__close {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--aia-fg-muted, #a1a1aa);
  font-size: 1.4rem;
  line-height: 1;
  cursor: pointer;
  border-radius: 6px;
}
.aia-reauth__close:hover {
  color: var(--aia-fg, #fafafa);
  background: rgba(255, 255, 255, 0.05);
}
.aia-reauth__ok {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--aia-success, #34d399);
  font-weight: 500;
}
</style>
