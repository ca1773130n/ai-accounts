<script setup lang="ts">
import { computed, watchEffect } from 'vue';
import { useSmartChat, useSmartScroll } from '@ai-accounts/vue-headless';
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

watchEffect(() => {
  chat.setConfigParser(props.configParser ?? null);
});

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
      :selected-model="chat.selectedModel.value"
      :backends="[]"
      @update:chat-mode="chat.setMode"
      @update:selected-backend="chat.selectBackend"
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
      @send="chat.send"
    />
  </div>
</template>

<style scoped>
.aia-smart-panel {
  display: flex; flex-direction: column; height: 100%;
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
