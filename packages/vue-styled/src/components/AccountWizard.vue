<script setup lang="ts">
import { ref } from 'vue';
import { useAccountWizard, type UseAccountWizardOptions } from '@ai-accounts/vue-headless';

const props = defineProps<{
  client: UseAccountWizardOptions['client'];
  kinds?: Array<{ id: string; display: string }>;
}>();

const emit = defineEmits<{
  done: [backendId: string];
  cancel: [];
}>();

const wiz = useAccountWizard({ client: props.client });
const apiKey = ref('');

const kinds = props.kinds ?? [
  { id: 'claude', display: 'Claude' },
  { id: 'opencode', display: 'OpenCode' },
  { id: 'gemini', display: 'Gemini' },
  { id: 'codex', display: 'Codex' },
];

wiz.start();

async function onPick(kind: string) {
  await wiz.pickKind(kind);
}

async function onSubmit() {
  await wiz.submitCredential('api_key', { api_key: apiKey.value });
  if (wiz.state.value === 'done' && wiz.backend.value) {
    emit('done', wiz.backend.value.id);
  }
}

function onRetry() {
  wiz.reset();
  wiz.start();
}
</script>

<template>
  <section class="aia-wizard">
    <header class="aia-wizard__header">
      <slot name="header">
        <h2>Connect an AI backend</h2>
      </slot>
    </header>

    <div v-if="wiz.state.value === 'picking_kind'" class="aia-wizard__kinds">
      <button
        v-for="k in kinds"
        :key="k.id"
        class="aia-btn aia-btn--kind"
        type="button"
        @click="onPick(k.id)"
      >
        {{ k.display }}
      </button>
    </div>

    <div v-else-if="wiz.state.value === 'detecting'" class="aia-wizard__status">
      Detecting {{ wiz.kind.value }} CLI…
    </div>

    <form
      v-else-if="wiz.state.value === 'entering_credential'"
      class="aia-wizard__form"
      @submit.prevent="onSubmit"
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

    <div v-else-if="wiz.state.value === 'validating'" class="aia-wizard__status">
      Validating credential…
    </div>

    <div v-else-if="wiz.state.value === 'done'" class="aia-wizard__success">
      <slot name="success">
        <p>&#10003; Connected successfully</p>
      </slot>
    </div>

    <div v-else-if="wiz.state.value === 'error'" class="aia-wizard__error">
      <p>{{ wiz.error.value }}</p>
      <button class="aia-btn" type="button" @click="onRetry">Try again</button>
    </div>
  </section>
</template>

<style scoped>
.aia-wizard {
  background: var(--aia-bg-elevated);
  border: 1px solid var(--aia-border);
  border-radius: var(--aia-radius-lg);
  padding: var(--aia-space-6);
  font-family: var(--aia-font-sans);
  color: var(--aia-fg);
  max-width: 520px;
}

.aia-wizard__header h2 {
  margin: 0 0 var(--aia-space-4);
  font-size: var(--aia-text-xl);
}

.aia-wizard__kinds {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--aia-space-3);
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

.aia-wizard__form {
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

.aia-wizard__status,
.aia-wizard__success,
.aia-wizard__error {
  padding: var(--aia-space-4) 0;
}

.aia-wizard__success {
  color: var(--aia-success);
}

.aia-wizard__error {
  color: var(--aia-danger);
}
</style>
