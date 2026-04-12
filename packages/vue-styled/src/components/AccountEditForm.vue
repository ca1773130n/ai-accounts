<script setup lang="ts">
import { reactive, ref, computed } from 'vue';
import type { BackendMetadata } from '@ai-accounts/ts-core';
import { useAiAccounts } from '@ai-accounts/vue-headless';

type Account = {
  id: string;
  kind: string;
  display_name: string;
  config: Record<string, unknown>;
};

const props = defineProps<{
  account: Account;
  metadata: BackendMetadata;
}>();

const emit = defineEmits<{
  (e: 'saved', account: Account): void;
  (e: 'cancel'): void;
}>();

const { client } = useAiAccounts();

const form = reactive({
  display_name: props.account.display_name,
  config: { ...props.account.config } as Record<string, unknown>,
});

const saving = ref(false);
const error = ref<string | null>(null);

const properties = computed(
  () =>
    ((props.metadata.config_schema as { properties?: Record<string, { type: string }> })
      ?.properties ?? {}) as Record<string, { type: string }>
);

async function submit() {
  saving.value = true;
  error.value = null;
  try {
    const updated = await client.updateBackend(props.account.id, {
      display_name: form.display_name,
      config: form.config,
    });
    emit('saved', updated as unknown as Account);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <form class="aia-account-edit" @submit.prevent="submit">
    <label>
      Display name
      <input v-model="form.display_name" type="text" required />
    </label>

    <div v-for="(_schema, key) in properties" :key="key" class="aia-field">
      <label>
        {{ key }}
        <input
          :value="form.config[key] ?? ''"
          :type="
            String(key).toLowerCase().includes('secret') ||
            String(key).toLowerCase().includes('key')
              ? 'password'
              : 'text'
          "
          @input="(e) => (form.config[key] = (e.target as HTMLInputElement).value)"
        />
      </label>
    </div>

    <div class="aia-actions">
      <button type="submit" :disabled="saving">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
      <button type="button" @click="emit('cancel')">Cancel</button>
    </div>

    <p v-if="error" class="aia-error">{{ error }}</p>
  </form>
</template>

<style scoped>
.aia-account-edit { display: flex; flex-direction: column; gap: 0.75rem; }
.aia-field { display: flex; }
.aia-actions { display: flex; gap: 0.5rem; }
.aia-error { color: var(--aia-error, #c00); }
</style>
