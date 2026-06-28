<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useAiAccounts } from '@ai-accounts/vue-headless'
import type { BackendDTO, ChatMode } from '@ai-accounts/ts-core'

/**
 * Compact horizontal selector strip exposing four bound properties
 * (Backend, Account, Model, ChatMode) for callers that prefer their
 * own chat-panel layout instead of `AiChatPanel`.
 *
 * Backend/account/model data is loaded directly from
 * `useAiAccounts().client` — no app-specific wrapper is required.
 *
 * Back-migrated from Agented (`b2ee00d~1`, restored in Agented v0.5.5).
 */

const props = withDefaults(
  defineProps<{
    /** Backend kind ("auto" or one of the kinds returned by listBackends). */
    backend: string
    /** BackendDTO id of the chosen account, or null to auto-pick. */
    accountId: string | null
    /** Selected model id, or null to auto-pick. */
    model: string | null
    /** When provided, render the chatMode radio strip on the right. */
    chatMode?: ChatMode
  }>(),
  {},
)

const emit = defineEmits<{
  (e: 'update:backend', value: string): void
  (e: 'update:accountId', value: string | null): void
  (e: 'update:model', value: string | null): void
  (e: 'update:chatMode', value: ChatMode): void
}>()

const chatModes: Array<{ value: ChatMode; label: string }> = [
  { value: 'single', label: 'Single' },
  { value: 'all', label: 'All' },
  { value: 'compound', label: 'Compound' },
]

const { client } = useAiAccounts()

/** All BackendDTO rows returned by the sidecar. One row per account
 *  per kind (e.g. two Claude rows if the user has two Claude accounts). */
const backends = ref<BackendDTO[]>([])
/** Models cache keyed by backend kind. Lazy-populated. */
const modelsByKind = ref<Record<string, string[]>>({})
const loading = ref(true)

/** Distinct backend kinds with at least one ready/registered row. */
const backendKinds = computed(() => {
  const seen = new Map<string, { kind: string; label: string }>()
  for (const b of backends.value) {
    if (!seen.has(b.kind)) {
      seen.set(b.kind, { kind: b.kind, label: backendLabel(b) })
    }
  }
  return Array.from(seen.values())
})

function backendLabel(b: BackendDTO): string {
  // Prefer a per-kind label so a kind with multiple accounts still shows
  // a single canonical name in the kind dropdown.
  const KIND_LABELS: Record<string, string> = {
    claude: 'Claude',
    codex: 'Codex',
    antigravity: 'Antigravity',
    opencode: 'OpenCode',
    deepseek: 'DeepSeek',
    qwen: 'Qwen',
  }
  return KIND_LABELS[b.kind] ?? b.kind
}

const activeKindRows = computed(() => {
  if (props.backend === 'auto') return []
  return backends.value.filter((b) => b.kind === props.backend)
})

const accountOptions = computed(() =>
  activeKindRows.value.map((b) => ({ id: b.id, label: b.display_name || b.id })),
)

const modelOptions = computed(() => modelsByKind.value[props.backend] ?? [])
const isAutoMode = computed(() => props.backend === 'auto')

async function loadModelsFor(kind: string) {
  if (modelsByKind.value[kind]) return
  const row = backends.value.find((b) => b.kind === kind)
  if (!row) return
  try {
    const { items } = await client.listModels(row.id)
    modelsByKind.value = { ...modelsByKind.value, [kind]: items.map((m) => m.id) }
  } catch {
    // Backend not yet ready / endpoint failed — leave models empty;
    // dropdown will render disabled.
  }
}

onMounted(async () => {
  try {
    const result = await client.listBackends()
    backends.value = result.items ?? []
    // Eagerly load models for the currently-selected kind so the Model
    // dropdown is populated on first render. Back-migrated from Agented.
    if (props.backend && props.backend !== 'auto') {
      await loadModelsFor(props.backend)
    }
  } catch {
    // Sidecar may be unreachable; selector will show only "Auto".
  } finally {
    loading.value = false
  }
})

// Reset the account / model when the backend kind changes.
watch(
  () => props.backend,
  (kind) => {
    emit('update:accountId', null)
    emit('update:model', null)
    if (kind && kind !== 'auto') void loadModelsFor(kind)
  },
)

function onBackendChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('update:backend', value)
  // Picking a specific kind forces single-mode (all/compound only
  // make sense in auto-routing mode). Back-migrated from Agented.
  if (value !== 'auto' && props.chatMode && props.chatMode !== 'single') {
    emit('update:chatMode', 'single')
  }
}

function onAccountChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('update:accountId', value || null)
}

function onModelChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('update:model', value || null)
}
</script>

<template>
  <div class="aia-chat-selector">
    <div class="aia-chat-selector__group">
      <label class="aia-chat-selector__label">Backend:</label>
      <select
        class="aia-chat-selector__select aia-chat-selector__select--backend"
        :value="backend"
        :disabled="loading"
        @change="onBackendChange"
      >
        <option value="auto">Auto</option>
        <option v-for="b in backendKinds" :key="b.kind" :value="b.kind">
          {{ b.label }}
        </option>
      </select>
    </div>

    <div class="aia-chat-selector__group">
      <label class="aia-chat-selector__label">Account:</label>
      <select
        class="aia-chat-selector__select aia-chat-selector__select--account"
        :value="accountId || ''"
        :disabled="isAutoMode || accountOptions.length === 0"
        @change="onAccountChange"
      >
        <option value="">Auto</option>
        <option v-for="a in accountOptions" :key="a.id" :value="a.id">
          {{ a.label }}
        </option>
      </select>
    </div>

    <div class="aia-chat-selector__group">
      <label class="aia-chat-selector__label">Model:</label>
      <select
        class="aia-chat-selector__select aia-chat-selector__select--model"
        :value="model || ''"
        :disabled="isAutoMode || modelOptions.length === 0"
        @change="onModelChange"
      >
        <option value="">Auto</option>
        <option v-for="m in modelOptions" :key="m" :value="m">
          {{ m }}
        </option>
      </select>
    </div>

    <div v-if="chatMode" class="aia-chat-selector__group aia-chat-selector__mode-group">
      <span class="aia-chat-selector__mode-separator" aria-hidden="true"></span>
      <label
        v-for="m in chatModes"
        :key="m.value"
        class="aia-chat-selector__mode-radio"
        :class="{ 'aia-chat-selector__mode-radio--active': chatMode === m.value }"
      >
        <input
          type="radio"
          name="aia-chat-selector-mode"
          :value="m.value"
          :checked="chatMode === m.value"
          @change="emit('update:chatMode', m.value)"
        />
        {{ m.label }}
      </label>
    </div>

    <slot name="trailing" />
  </div>
</template>

<style scoped>
.aia-chat-selector {
  display: flex;
  align-items: center;
  gap: var(--aia-space-3, 12px);
  padding: var(--aia-space-2, 8px) var(--aia-space-4, 16px);
  background: var(--aia-bg-elevated, #141414);
  border-bottom: 1px solid var(--aia-border, #27272a);
}
.aia-chat-selector__group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.aia-chat-selector__label {
  font-size: var(--aia-text-xs, 12px);
  color: var(--aia-fg-muted, #a1a1aa);
  white-space: nowrap;
}
.aia-chat-selector__select {
  background: var(--aia-bg, #0a0a0a);
  color: var(--aia-fg, #fafafa);
  border: 1px solid var(--aia-border, #27272a);
  border-radius: var(--aia-radius, 6px);
  padding: 4px 8px;
  font-size: var(--aia-text-sm, 13px);
  outline: none;
  cursor: pointer;
  min-width: 80px;
}
.aia-chat-selector__select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.aia-chat-selector__select:focus {
  border-color: var(--aia-primary, #7c3aed);
}
.aia-chat-selector__mode-separator {
  width: 1px;
  height: 20px;
  background: var(--aia-border, #27272a);
  margin-right: 4px;
}
.aia-chat-selector__mode-group {
  gap: 2px;
}
.aia-chat-selector__mode-radio {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--aia-text-xs, 12px);
  color: var(--aia-fg-muted, #a1a1aa);
  cursor: pointer;
  padding: 3px 8px;
  border-radius: var(--aia-radius-sm, 4px);
  transition: color 0.15s;
  white-space: nowrap;
}
.aia-chat-selector__mode-radio:hover {
  color: var(--aia-fg, #fafafa);
}
.aia-chat-selector__mode-radio--active {
  color: var(--aia-primary-hover, #8b5cf6);
  font-weight: 600;
}
.aia-chat-selector__mode-radio input[type='radio'] {
  appearance: none;
  -webkit-appearance: none;
  width: 12px;
  height: 12px;
  border: 1.5px solid var(--aia-fg-subtle, #71717a);
  border-radius: 50%;
  cursor: pointer;
  position: relative;
  flex-shrink: 0;
}
.aia-chat-selector__mode-radio input[type='radio']:checked {
  border-color: var(--aia-primary, #7c3aed);
}
.aia-chat-selector__mode-radio input[type='radio']:checked::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--aia-primary, #7c3aed);
}
</style>
