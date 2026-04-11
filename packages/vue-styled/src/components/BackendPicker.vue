<script setup lang="ts">
import { onMounted } from 'vue';
import { useBackendRegistry } from '@ai-accounts/vue-headless';

const props = defineProps<{
  installStatus?: Record<string, { installed: boolean; version: string | null }>;
}>();

const emit = defineEmits<{
  (e: 'pick', kind: string): void;
}>();

const registry = useBackendRegistry();

function statusFor(kind: string) {
  return props.installStatus ? props.installStatus[kind] : undefined;
}

onMounted(async () => {
  if (!registry.loaded.value) await registry.load();
});
</script>

<template>
  <ul class="aia-backend-picker">
    <li v-for="meta in registry.backends.value" :key="meta.kind">
      <button type="button" @click="emit('pick', meta.kind)">
        <img v-if="meta.icon_url" :src="meta.icon_url" :alt="meta.display_name" />
        <div class="aia-backend-info">
          <strong>{{ meta.display_name }}</strong>
          <template v-if="statusFor(meta.kind)">
            <span v-if="statusFor(meta.kind)!.installed" class="aia-installed">
              installed{{
                statusFor(meta.kind)!.version ? ' v' + statusFor(meta.kind)!.version : ''
              }}
            </span>
            <span v-else class="aia-not-installed">not detected</span>
          </template>
        </div>
      </button>
    </li>
  </ul>
</template>

<style scoped>
.aia-backend-picker { display: grid; gap: 0.75rem; list-style: none; padding: 0; }
.aia-backend-picker button {
  display: flex; gap: 0.75rem; width: 100%; padding: 0.75rem 1rem;
  background: var(--aia-card-bg, #1a1a1a); color: var(--aia-card-fg, #eee);
  border: 1px solid var(--aia-border, #333); border-radius: 8px;
  cursor: pointer; text-align: left;
}
.aia-backend-picker button:hover { background: var(--aia-card-hover, #222); }
.aia-installed { color: var(--aia-ok, #4c8); }
.aia-not-installed { color: var(--aia-warn, #c83); }
</style>
