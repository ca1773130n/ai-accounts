<script setup lang="ts">
import { computed, ref, watch, watchEffect, onMounted } from 'vue';
import { useSmartChat, useSmartScroll, useAiAccounts } from '@ai-accounts/vue-headless';
import type { BackendDTO, BackendOption } from '@ai-accounts/ts-core';
import ChatBubble from './ChatBubble.vue';
import ChatControls from './ChatControls.vue';
import ChatInput from './ChatInput.vue';
import AllModeResponses from './AllModeResponses.vue';
import CompoundSynthesis from './CompoundSynthesis.vue';
import FinalizationBanner from './FinalizationBanner.vue';
import ProcessGroup from './ProcessGroup.vue';

const props = withDefaults(defineProps<{
  density?: 'minimal' | 'detailed';
  defaultBackend?: string;
  defaultModel?: string;
  placeholder?: string;
  welcomeTitle?: string;
  welcomeSubtitle?: string;
  readOnly?: boolean;
  entityLabel?: string;
  bannerTitle?: string;
  bannerButtonLabel?: string;
  configParser?: (content: string) => Record<string, unknown> | null;
  showProcessGroups?: boolean;
  showActions?: boolean;
}>(), {
  density: 'minimal',
  placeholder: 'Type a message...',
  welcomeTitle: 'AI Chat',
  welcomeSubtitle: 'Send a message to get started',
  showProcessGroups: undefined as unknown as boolean,
  showActions: undefined as unknown as boolean,
});

const resolvedShowProcessGroups = computed(() =>
  props.showProcessGroups ?? (props.density === 'detailed'),
);
const resolvedShowActions = computed(() =>
  props.showActions ?? (props.density === 'detailed'),
);

const emit = defineEmits<{
  finalize: [config: Record<string, unknown> | null];
}>();

const chat = useSmartChat();
const scroll = useSmartScroll();
const { client } = useAiAccounts();
const backends = ref<BackendDTO[]>([]);
// Models per backend kind, populated lazily from /api/v1/backends/{id}/models.
// Empty arrays render as a disabled dropdown; once loaded, the user can pick.
const modelsByKind = ref<Record<string, string[]>>({});
const backendOptions = computed<BackendOption[]>(() =>
  Array.from(new Set(backends.value.map(b => b.kind))).map(kind => {
    const forKind = backends.value.filter(b => b.kind === kind);
    return {
      kind,
      displayName: kind,
      // Account dropdown shows display_name (typically the email); the id
      // is what gets sent to the API as account_id.
      accounts: forKind.map(b => ({ id: b.id, label: b.display_name || b.id })),
      models: modelsByKind.value[kind] ?? [],
    };
  }),
);

async function loadModelsFor(backend: BackendDTO) {
  if (modelsByKind.value[backend.kind]) return;
  try {
    const { items } = await client.listModels(backend.id);
    modelsByKind.value = { ...modelsByKind.value, [backend.kind]: items.map(m => m.id) };
  } catch {
    // Backend not yet ready / endpoint failed — leave models empty; user can retry.
  }
}

async function loadAllModels() {
  await Promise.all(backends.value.filter(b => b.status === 'ready').map(loadModelsFor));
  // If no model is yet selected, default to the first model of the first ready backend
  // so handleSend never sends an empty model string (the API rejects it with 400).
  if (!chat.selectedModel.value) {
    for (const opt of backendOptions.value) {
      if (opt.models.length > 0) {
        chat.selectedModel.value = opt.models[0]!;
        if (!chat.selectedBackend.value) chat.selectedBackend.value = opt.kind;
        break;
      }
    }
  }
}

watchEffect(() => {
  chat.setConfigParser(props.configParser ?? null);
});

onMounted(async () => {
  try {
    const result = await client.listBackends();
    backends.value = result.items ?? [];
    await loadAllModels();
  } catch (e) {
    // listBackends may fail before sidecar is ready; ignore — user can retry by sending
  }
});

// The chat session is bound server-side to the backend it was created with.
// Changing the backend (or specific account) in the dropdown means the next
// message must go through a fresh session — otherwise the request is honored
// against the old binding and the user sees responses from the wrong model.
// Clear the session when either selection changes; handleSend will create a
// new one on the next message.
watch(
  () => [chat.selectedBackend.value, chat.selectedAccount.value],
  ([newKind, newAccount], [oldKind, oldAccount]) => {
    if (!chat.sessionId.value) return;
    if (newKind !== oldKind || newAccount !== oldAccount) {
      chat.resetSession();
    }
  },
);

function pickBackendFor(kind: string | null, accountId: string | null = null): BackendDTO | null {
  if (accountId) {
    const exact = backends.value.find(b => b.id === accountId);
    if (exact) return exact;
  }
  const pool = kind ? backends.value.filter(b => b.kind === kind) : backends.value;
  return pool.find(b => b.status === 'ready') ?? pool[0] ?? null;
}

async function handleSend(content: string) {
  if (!chat.sessionId.value) {
    // Refresh backends if none loaded yet
    if (backends.value.length === 0) {
      try {
        const result = await client.listBackends();
        backends.value = result.items ?? [];
        await loadAllModels();
      } catch {
        chat.error.value = 'Unable to load backends from sidecar';
        return;
      }
    }
    const preferredKind = chat.selectedBackend.value ?? props.defaultBackend ?? null;
    const preferredAccount = chat.selectedAccount.value;
    const backend = pickBackendFor(preferredKind, preferredAccount);
    if (!backend) {
      chat.error.value = 'No backend available — add an account first';
      return;
    }
    // Resolve a non-empty model. selectBackend() clears selectedModel, so on
    // the first send after a backend switch we'd otherwise post '' and the
    // server would reject with 400 ("Expected str of length >= 1 at .model").
    // Lazy-load models for this backend if missing, then default to its first.
    let model = chat.selectedModel.value ?? props.defaultModel ?? '';
    if (!model) {
      await loadModelsFor(backend);
      const candidates = modelsByKind.value[backend.kind] ?? [];
      if (candidates.length > 0) {
        model = candidates[0]!;
        chat.selectedModel.value = model;
      }
    }
    if (!model) {
      chat.error.value = `No models available for ${backend.kind}`;
      return;
    }
    try {
      await chat.createSession(backend.id, model);
    } catch (e) {
      chat.error.value = e instanceof Error ? e.message : String(e);
      return;
    }
  }
  await chat.send(content);
}

async function handleFinalize() {
  const cfg = await chat.finalize();
  emit('finalize', cfg);
}
</script>

<template>
  <div class="aia-smart-panel">
    <!-- Controls bar (detailed mode only) -->
    <ChatControls
      v-if="density === 'detailed'"
      :chat-mode="chat.chatMode.value"
      :selected-backend="chat.selectedBackend.value"
      :selected-account="chat.selectedAccount.value"
      :selected-model="chat.selectedModel.value"
      :backends="backendOptions"
      @update:chat-mode="chat.setMode"
      @update:selected-backend="chat.selectBackend"
      @update:selected-account="(v: string | null) => chat.selectedAccount.value = v"
      @update:selected-model="(v: string | null) => chat.selectedModel.value = v"
    />

    <!-- Messages area -->
    <div ref="scroll.containerRef" class="aia-smart-panel__messages">
      <!-- Welcome screen -->
      <div v-if="chat.messages.value.length === 0 && !chat.isStreaming.value" class="aia-smart-panel__welcome">
        <div class="aia-smart-panel__welcome-icon">AI</div>
        <h3 class="aia-smart-panel__welcome-title">{{ welcomeTitle }}</h3>
        <p class="aia-smart-panel__welcome-sub">{{ welcomeSubtitle }}</p>
      </div>

      <!-- Chat messages -->
      <ChatBubble
        v-for="msg in chat.messages.value" :key="msg.id"
        :role="msg.role"
        :content="msg.content"
        :timestamp="msg.created_at"
        :show-actions="resolvedShowActions"
        :all-messages="chat.messages.value"
      />

      <!-- Single-mode streaming bubble -->
      <ChatBubble
        v-if="chat.isStreaming.value && chat.chatMode.value === 'single' && chat.streamingContent.value"
        role="assistant"
        :content="chat.streamingContent.value"
        :streaming="true"
      />

      <!-- All / Compound mode backend responses -->
      <AllModeResponses
        v-if="chat.backendResponses.value.size > 0"
        :responses="chat.backendResponses.value"
        :collapsible="chat.chatMode.value === 'compound'"
      />

      <!-- Compound synthesis -->
      <CompoundSynthesis
        v-if="chat.synthesisState.value"
        :state="chat.synthesisState.value"
      />

      <!-- Process groups (tool calls, reasoning, code execution) -->
      <div
        v-if="resolvedShowProcessGroups && chat.processGroups.groups.value.size > 0"
        class="process-groups"
      >
        <ProcessGroup
          v-for="[id, group] in chat.processGroups.groups.value"
          :key="id"
          :id="group.id"
          :type="group.type"
          :label="group.label"
          :timestamp="group.timestamp"
          :is-expanded="group.isExpanded"
          @toggle="chat.processGroups.toggleGroup(id)"
        >
          <pre>{{ group.content }}</pre>
        </ProcessGroup>
      </div>

      <!-- Finalization banner -->
      <slot
        v-if="$slots.finalization"
        name="finalization"
        :state="{ canFinalize: chat.canFinalize, isFinalizing: chat.isFinalizing }"
      />
      <FinalizationBanner
        v-else-if="chat.canFinalize.value && entityLabel"
        :title="bannerTitle ?? 'Ready to finalize'"
        :button-label="bannerButtonLabel ?? 'Finalize'"
        :entity-label="entityLabel"
        :is-finalizing="chat.isFinalizing.value"
        @finalize="handleFinalize"
      />

      <!-- Scroll anchor -->
      <div class="aia-smart-panel__anchor" />
    </div>

    <!-- Scroll-to-bottom button -->
    <button
      v-if="scroll.showScrollButton.value"
      class="aia-smart-panel__scroll-btn"
      @click="scroll.scrollToBottom"
    >
      &#8595;
    </button>

    <!-- Error banner -->
    <div v-if="chat.error.value" class="aia-smart-panel__error">
      {{ chat.error.value }}
    </div>

    <!-- Input -->
    <ChatInput
      v-if="!readOnly"
      :placeholder="placeholder"
      :is-streaming="chat.isStreaming.value"
      @send="handleSend"
    />
  </div>
</template>

<style scoped>
.aia-smart-panel {
  display: flex; flex-direction: column; height: 100%; width: 100%;
  flex: 1 1 auto; min-width: 0;
  font-family: var(--aia-font-sans, system-ui, sans-serif);
  background: var(--aia-bg, #0a0a0a); color: var(--aia-fg, #fafafa);
  position: relative;
}
.aia-smart-panel__messages {
  flex: 1; overflow-y: auto; padding: var(--aia-space-3, 12px) var(--aia-space-4, 16px);
}
/* Welcome */
.aia-smart-panel__welcome {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  min-height: 200px; gap: var(--aia-space-2, 8px); text-align: center;
  padding: var(--aia-space-8, 32px);
}
.aia-smart-panel__welcome-icon {
  width: 48px; height: 48px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  background: rgba(124,58,237,0.15); color: var(--aia-primary-hover, #8b5cf6);
  font-weight: 700; font-size: var(--aia-text-lg, 18px); margin-bottom: var(--aia-space-2, 8px);
}
.aia-smart-panel__welcome-title {
  margin: 0; font-size: var(--aia-text-xl, 24px); font-weight: 700; color: var(--aia-fg, #fafafa);
}
.aia-smart-panel__welcome-sub {
  margin: 0; font-size: var(--aia-text-sm, 14px); color: var(--aia-fg-muted, #a1a1aa);
}
/* Scroll button */
.aia-smart-panel__scroll-btn {
  position: absolute; bottom: 80px; right: var(--aia-space-4, 16px);
  width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--aia-border, #27272a);
  background: var(--aia-bg-elevated, #141414); color: var(--aia-fg, #fafafa);
  cursor: pointer; font-size: var(--aia-text-base, 16px); display: flex; align-items: center; justify-content: center;
  box-shadow: var(--aia-shadow-sm, 0 1px 2px rgba(0,0,0,0.4));
  transition: background var(--aia-transition, 150ms ease-out);
}
.aia-smart-panel__scroll-btn:hover { background: var(--aia-bg-hover, #1f1f1f); }
/* Error */
.aia-smart-panel__error {
  padding: var(--aia-space-2, 8px) var(--aia-space-3, 12px);
  background: rgba(239,68,68,0.1); color: var(--aia-danger, #ef4444);
  font-size: var(--aia-text-sm, 14px); border-top: 1px solid rgba(239,68,68,0.2);
}
.aia-smart-panel__anchor { height: 1px; }
</style>
