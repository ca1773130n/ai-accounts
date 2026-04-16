<script setup lang="ts">
interface Props {
  title: string
  buttonLabel: string
  entityLabel: string
  entityName?: string
  isFinalizing?: boolean
}

withDefaults(defineProps<Props>(), {
  isFinalizing: false,
})

const emit = defineEmits<{
  finalize: []
}>()
</script>

<template>
  <div class="finalization-banner">
    <div class="banner-content">
      <h3 class="banner-title">{{ title }}</h3>
      <p class="banner-description">
        Your {{ entityLabel }}{{ entityName ? ': ' + entityName : '' }} is ready.
        Click the button to finalize.
      </p>
    </div>
    <button
      class="banner-button"
      :disabled="isFinalizing"
      @click="emit('finalize')"
    >
      {{ isFinalizing ? 'Creating...' : buttonLabel }}
    </button>
  </div>
</template>

<style scoped>
.finalization-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  margin: 8px 0;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--aia-accent-bg, #1a2744), var(--aia-bg-secondary, #1a1a2e));
  border: 1px solid var(--aia-accent, #3b82f6);
}
.banner-content {
  flex: 1;
  min-width: 0;
}
.banner-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--aia-text, #e0e0e0);
}
.banner-description {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--aia-text-muted, #888);
}
.banner-button {
  flex-shrink: 0;
  padding: 8px 16px;
  border-radius: 6px;
  border: none;
  background: var(--aia-accent, #3b82f6);
  color: white;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}
.banner-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.banner-button:hover:not(:disabled) {
  filter: brightness(1.1);
}
</style>
